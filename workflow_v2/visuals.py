"""驗證視覺模型的結構與數學一致性；無效資料回退為文字版面。"""
import math
import re
from fractions import Fraction

MODEL_TYPES=['none','icon_groups','bar_model','ratio_arrows','compare_ab','concept_map','number_line','venn_diagram','spatial_scene']
ICONS=['circle','square','star','heart','triangle','diamond','cup','drop','block']
MAX_GROUPS=4;MAX_ICONS=12;MAX_BARS=4;MAX_PARTS=12;MAX_CHILDREN=5;MAX_ITEMS=3
CAPS={'title':20,'label':8,'unit':4,'root':8,'child_label':6,'example':14,'note':14,'side_title':12,'item':16,'value':14}
LEGACY_TO_NEW={'bullet_with_image':'Text_Visual','quiz_qa':'Question','two_column_comparison':'Two_Column',
               'summary_checklist':'Summary','code_walkthrough':'Steps','title_hero':'Cover'}
LAYOUT_MODELS={'Text_Visual':{'icon_groups','bar_model','ratio_arrows','concept_map','number_line','venn_diagram','spatial_scene'},
               'Two_Column':{'compare_ab'},
               'Question':{'icon_groups','bar_model','ratio_arrows','compare_ab','number_line','venn_diagram','spatial_scene'},
               'Steps':{'ratio_arrows','bar_model','icon_groups','number_line'},
               'Summary':{'concept_map'}}

def _string(n):return {'type':'string','maxLength':n}
def _object(properties,required):
    return {'type':'object','properties':properties,'required':required,'additionalProperties':False}
_NUM={'type':'number'}
_SIDE=_object({'title':_string(CAPS['side_title']),
               'items':{'type':'array','maxItems':MAX_ITEMS,'items':_string(CAPS['item'])},
               'value':_string(CAPS['value'])},['title'])
VISUAL_MODEL=_object({
    'type':{'enum':MODEL_TYPES},
    'intersection':{'type':'array','maxItems':3,'items':_string(CAPS['item'])},
    'relation':{'enum':['in','on','under','next_to','behind','in_front_of','between']},
    'object_label':_string(18),
    'references':{'type':'array','minItems':1,'maxItems':2,'items':_string(18)},
    'minimum':_NUM,'maximum':_NUM,
    'points':{'type':'array','minItems':1,'maxItems':4,'items':_object({
        'label':_string(CAPS['label']),'value':_NUM},['label','value'])},
    'title':_string(CAPS['title']),
    'groups':{'type':'array','maxItems':MAX_GROUPS,'items':_object({
        'label':_string(CAPS['label']),'icon':{'enum':ICONS},
        'count':{'type':'integer','minimum':1,'maximum':60}},['label','icon','count'])},
    'bars':{'type':'array','maxItems':MAX_BARS,'items':_object({
        'label':_string(CAPS['label']),'parts':{'type':'integer','minimum':1,'maximum':MAX_PARTS},
        'unit_value':_NUM,'total':_NUM,'unknown':{'type':'boolean'},'unit':_string(CAPS['unit'])},
        ['label','parts'])},
    'from':{'type':'array','minItems':2,'maxItems':2,'items':_NUM},
    'to':{'type':'array','minItems':2,'maxItems':2,'items':_NUM},
    'op':_string(8),
    'labels':{'type':'array','maxItems':2,'items':_string(CAPS['label'])},
    'units':{'type':'array','maxItems':2,'items':_string(CAPS['unit'])},
    'left':_SIDE,'right':_SIDE,
    'root':_string(CAPS['root']),
    'children':{'type':'array','maxItems':MAX_CHILDREN,'items':_object({
        'label':_string(CAPS['child_label']),'example':_string(CAPS['example']),
        'note':_string(CAPS['note'])},['label'])},
},['type'])

def number(value):
    """Return a Fraction for an int/float/str number, else raise ValueError."""
    if isinstance(value,bool) or value is None:raise ValueError('數值無效')
    if isinstance(value,(int,Fraction)):return Fraction(value)
    if isinstance(value,float):
        if not math.isfinite(value):raise ValueError('數值無效')
        return Fraction(str(value))
    try:return Fraction(str(value).strip())
    except (ValueError,ZeroDivisionError) as exc:raise ValueError('數值無效') from exc

def plain(value):
    """int when integral, else float (JSON friendly)."""
    frac=number(value)
    return int(frac) if frac.denominator==1 else float(frac)

def _text(value,cap,name,required=False):
    if value is None:value=''
    if not isinstance(value,str):raise ValueError(f'{name}必須是文字')
    value=value.strip()
    if required and not value:raise ValueError(f'{name}不得空白')
    if len(value)>cap:raise ValueError(f'{name}超過{cap}字')
    return value

def _op(value):
    text=re.sub(r'\s+','',str(value or '')).replace('x','×').replace('X','×').replace('*','×').replace('/','÷')
    match=re.fullmatch(r'([×÷])(\d+(?:\.\d+)?)',text)
    if not match or Fraction(match[2])==0:raise ValueError('op 格式需為 ×3 或 ÷5')
    return match[1],Fraction(match[2]),match[1]+match[2]

def _icon_groups(vm):
    groups=vm.get('groups')
    if not isinstance(groups,list) or not 1<=len(groups)<=MAX_GROUPS:raise ValueError('groups 需 1 至 4 組')
    result=[]
    for group in groups:
        if not isinstance(group,dict):raise ValueError('group 格式錯誤')
        count=number(group.get('count'))
        if count.denominator!=1 or count<1:raise ValueError('count 需為正整數')
        icon=group.get('icon') if group.get('icon') in ICONS else 'circle'
        result.append({'label':_text(group.get('label'),CAPS['label'],'label',True),'icon':icon,
                       'count':min(60,int(count))})
    return {'groups':result}

def _bar_model(vm):
    bars=vm.get('bars')
    if not isinstance(bars,list) or not 1<=len(bars)<=MAX_BARS:raise ValueError('bars 需 1 至 4 條')
    result=[]
    for bar in bars:
        if not isinstance(bar,dict):raise ValueError('bar 格式錯誤')
        parts=number(bar.get('parts'))
        if parts.denominator!=1 or not 1<=parts<=MAX_PARTS:raise ValueError('parts 需為 1 至 12')
        clean={'label':_text(bar.get('label'),CAPS['label'],'label',True),'parts':int(parts)}
        unit_value=total=None
        if bar.get('unit_value') not in (None,''):
            unit_value=number(bar['unit_value'])
            if unit_value<=0:raise ValueError('unit_value 需為正數')
            clean['unit_value']=plain(unit_value)
        if bar.get('total') not in (None,''):
            total=number(bar['total'])
            if total<=0:raise ValueError('total 需為正數')
            clean['total']=plain(total)
        if unit_value is not None and total is not None and unit_value*int(parts)!=total:
            raise ValueError('份數×每份與總量不一致')
        clean['unknown']=bool(bar.get('unknown'))
        if clean['unknown'] and 'total' in clean:raise ValueError('未知量不得同時給總量')
        clean['unit']=_text(bar.get('unit'),CAPS['unit'],'unit')
        result.append(clean)
    return {'bars':result}

def _ratio_arrows(vm):
    source,target=vm.get('from'),vm.get('to')
    for pair in (source,target):
        if not isinstance(pair,list) or len(pair)!=2:raise ValueError('from/to 需兩個數')
    a,b=[number(x) for x in source];c,d=[number(x) for x in target]
    if min(a,b,c,d)<=0:raise ValueError('比的數需為正數')
    sign,factor,op=_op(vm.get('op'))
    if sign=='×':ok=(a*factor==c and b*factor==d)
    else:ok=(a/factor==c and b/factor==d)
    if not ok:raise ValueError('箭頭運算與兩列數字不一致')
    labels=[_text(x,CAPS['label'],'labels') for x in (vm.get('labels') or [])][:2]
    units=[_text(x,CAPS['unit'],'units') for x in (vm.get('units') or [])][:2]
    return {'from':[plain(a),plain(b)],'to':[plain(c),plain(d)],'op':op,'labels':labels,'units':units}

def _side(side,name):
    if not isinstance(side,dict):raise ValueError(f'{name}格式錯誤')
    items=side.get('items') or []
    if not isinstance(items,list) or len(items)>MAX_ITEMS:raise ValueError('items 最多 3 項')
    return {'title':_text(side.get('title'),CAPS['side_title'],name+'標題',True),
            'items':[_text(x,CAPS['item'],name+'項目',True) for x in items],
            'value':_text(side.get('value'),CAPS['value'],name+'數值')}

def _compare_ab(vm):
    return {'left':_side(vm.get('left'),'左側'),'right':_side(vm.get('right'),'右側')}

def _concept_map(vm):
    children=vm.get('children')
    if not isinstance(children,list) or not 2<=len(children)<=MAX_CHILDREN:raise ValueError('children 需 2 至 5 項')
    result=[]
    for child in children:
        if not isinstance(child,dict):raise ValueError('child 格式錯誤')
        result.append({'label':_text(child.get('label'),CAPS['child_label'],'label',True),
                       'example':_text(child.get('example'),CAPS['example'],'example'),
                       'note':_text(child.get('note'),CAPS['note'],'note')})
    return {'root':_text(vm.get('root'),CAPS['root'],'root',True),'children':result}

def _number_line(vm):
    low,high=number(vm.get('minimum')),number(vm.get('maximum'))
    if high<=low or high-low>1000:raise ValueError('數線範圍需遞增且不超過1000')
    points=vm.get('points')
    if not isinstance(points,list) or not 1<=len(points)<=4:raise ValueError('數線需要一至四個點')
    result=[]
    for point in points:
        value=number(point.get('value'))
        if not low<=value<=high:raise ValueError('數線點超出範圍')
        result.append({'label':_text(point.get('label'),CAPS['label'],'label',True),'value':plain(value)})
    return {'minimum':plain(low),'maximum':plain(high),'points':result}

def _venn_diagram(vm):
    sides=_compare_ab(vm)
    common=vm.get('intersection') or []
    if not isinstance(common,list) or len(common)>3:raise ValueError('維恩圖共同項目最多三項')
    common=[_text(x,CAPS['item'],'共同項目',True) for x in common]
    left,right=sides['left']['items'],sides['right']['items']
    # Classifications belong to the model. Conflicting regions are not silently
    # moved or invented by the renderer.
    if (set(left)&set(right)) or set(common)&(set(left)|set(right)):
        raise ValueError('維恩圖同一項目不可重複放入不同區域')
    return {**sides,'intersection':common}

def _spatial_scene(vm):
    relation=vm.get('relation')
    if relation not in ('in','on','under','next_to','behind','in_front_of','between'):
        raise ValueError('未知位置關係')
    refs=vm.get('references')
    needed=2 if relation=='between' else 1
    if not isinstance(refs,list) or len(refs)!=needed:raise ValueError('位置圖參照物數量不符')
    return {'relation':relation,'object_label':_text(vm.get('object_label'),18,'主體',True),
            'references':[_text(x,18,'參照物',True) for x in refs]}

_BUILD={'venn_diagram':_venn_diagram,'spatial_scene':_spatial_scene,'number_line':_number_line,'icon_groups':_icon_groups,'bar_model':_bar_model,'ratio_arrows':_ratio_arrows,
        'compare_ab':_compare_ab,'concept_map':_concept_map}

def sanitize(vm,layout=None):
    """Return (clean_model or None, reason). Never raises."""
    try:
        if vm in (None,{},[]) or not isinstance(vm,dict):return None,''
        kind=vm.get('type')
        if kind in (None,'none',''):return None,''
        if kind not in _BUILD:return None,'未知圖解類型'
        layout=LEGACY_TO_NEW.get(layout,layout)
        if layout is not None and kind not in LAYOUT_MODELS.get(layout,set()):
            return None,f'{layout} 版型不支援 {kind}'
        clean={'type':kind,'title':_text(vm.get('title'),CAPS['title'],'title')}
        clean.update(_BUILD[kind](vm))
        return clean,''
    except (ValueError,TypeError,KeyError,AttributeError,ArithmeticError) as exc:
        return None,str(exc)[:120]

def sanitize_slide(slide):
    """Validate slide['visual_model'] in place; return the drop reason ('' when kept/absent)."""
    if 'visual_model' not in slide:return ''
    clean,reason=sanitize(slide.get('visual_model'),slide.get('layout_id'))
    if clean is None:slide.pop('visual_model',None)
    else:slide['visual_model']=clean
    return reason

def model_numbers(vm):
    """Every number a model displays, as Fractions (for consistency checks)."""
    if not vm:return []
    kind=vm.get('type');values=[]
    if kind=='icon_groups':values=[g['count'] for g in vm.get('groups',[])]
    elif kind=='bar_model':
        for bar in vm.get('bars',[]):
            values.append(bar['parts'])
            for key in ('unit_value','total'):
                if key in bar:values.append(bar[key])
    elif kind=='ratio_arrows':values=list(vm.get('from',[]))+list(vm.get('to',[]))
    elif kind=='number_line':values=[p['value'] for p in vm.get('points',[])]
    return [Fraction(str(v)) for v in values]

def model_text(vm):
    """Words shown by a model (used for QA of entity coverage)."""
    if not vm:return ''
    parts=[vm.get('title','')]
    kind=vm.get('type')
    if kind=='icon_groups':parts+=[g['label'] for g in vm.get('groups',[])]
    elif kind=='bar_model':parts+=[b['label'] for b in vm.get('bars',[])]
    elif kind=='ratio_arrows':parts+=list(vm.get('labels',[]))+list(vm.get('units',[]))
    elif kind=='number_line':parts+=[p['label']+' '+str(p['value']) for p in vm.get('points',[])]
    elif kind in ('compare_ab','venn_diagram'):
        for side in (vm.get('left',{}),vm.get('right',{})):
            parts+=[side.get('title','')]+list(side.get('items',[]))+[side.get('value','')]
        if kind=='venn_diagram':parts+=vm.get('intersection',[])
    elif kind=='spatial_scene':parts+=[vm.get('object_label',''),vm.get('relation','').replace('_',' ')]+vm.get('references',[])
    elif kind=='concept_map':
        parts.append(vm.get('root',''))
        for child in vm.get('children',[]):parts+=[child.get('label',''),child.get('example',''),child.get('note','')]
    return ' '.join(p for p in parts if p)

def model_caption(vm):
    """Keep the diagram's facts and classification when a page needs reflow."""
    if not vm:return ''
    kind=vm.get('type')
    if kind=='venn_diagram':
        return '\n'.join([side['title']+'：'+'、'.join(side.get('items',[]))
            for side in (vm['left'],vm['right'])]+['共同點：'+'、'.join(vm.get('intersection',[]))])
    if kind=='number_line':return '數線上的點：'+'、'.join(f"{p['label']}({p['value']:g})" for p in vm['points'])
    if kind=='spatial_scene':return vm['object_label']+' '+vm['relation'].replace('_',' ')+' '+' / '.join(vm['references'])
    if kind=='ratio_arrows':return f"{vm['from'][0]}:{vm['from'][1]} → {vm['to'][0]}:{vm['to'][1]}（{vm['op']}）"
    return model_text(vm)
