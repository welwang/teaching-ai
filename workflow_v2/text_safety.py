"""Text normalization at document boundaries."""
import re


def xml_text(value):
    """Keep XML 1.0 text characters, including tabs and line breaks."""
    return ''.join(char for char in str(value) if ord(char) in (9, 10, 13) or
                   0x20 <= ord(char) <= 0xD7FF or 0xE000 <= ord(char) <= 0xFFFD or
                   0x10000 <= ord(char) <= 0x10FFFF)


_MATH_SYMBOLS={
    'rightarrow':'→','to':'→','leftarrow':'←','times':'×','div':'÷',
    'cdot':'·','le':'≤','leq':'≤','ge':'≥','geq':'≥',
    'neq':'≠','approx':'≈','pm':'±','degree':'°','circ':'°',
}
_COMMAND=re.compile(r'\\('+ '|'.join(sorted(_MATH_SYMBOLS,key=len,reverse=True)) +r')(?![A-Za-z])')
_SIMPLE_FRAC=re.compile(r'\\frac\{([^{}]+)\}\{([^{}]+)\}')
_SIMPLE_ROOT=re.compile(r'\\sqrt\{([^{}]+)\}')


def format_teaching_text(value):
    """Repair known OpenXML/JSON escapes and display basic math as readable text.

    Unrecognized commands are preserved rather than guessed away. In particular,
    ordinary words such as 'times' and currency dollar signs must stay intact.
    """
    text=str(value)
    text=re.sub(r'(?i)(?:_x000d_|\r)\s*(?:r?ightarrow)(?![A-Za-z])',' → ',text)
    text=re.sub(r'(?i)(?:_x000d_|\r)\s*(?:r?leftarrow)(?![A-Za-z])',' ← ',text)
    text=re.sub(r'(?i)_x000d_|\r\n?|_x000a_','\n',text)
    text=re.sub(r'(?i)_x0009_','\t',text)
    text=_SIMPLE_FRAC.sub(lambda m:f'{m[1]}/{m[2]}',text)
    text=_SIMPLE_ROOT.sub(lambda m:f'√({m[1]})',text)
    text=_COMMAND.sub(lambda m:_MATH_SYMBOLS[m[1]],text)
    text=re.sub(r'-->|->','→',text)
    text=re.sub(r'\\(?:left|right)(?![A-Za-z])','',text)
    text=re.sub(r'\\(?:qquad|quad)(?![A-Za-z])',' ',text)
    text=re.sub(r'\\[,;!]',' ',text)
    text=re.sub(r'\\[()\[\]]','',text)
    text=re.sub(r'(?<!\\)\$([^$\n]+)\$',lambda m:m[1] if
                ('\\' in m[1] or re.search(r'[=+*/:^×÷≤≥≠≈→←]',m[1]) or
                 not re.search(r'\s',m[1])) else m[0],text)
    return xml_text(text)


_OPEN='〔\\[［【(（<《'
_CLOSE='〕\\]］】)）>》'
_RESIDUE_SUBS=[
    # bracketed pointers to the teacher notes, e.g. 〔後續原文見教師備註〕
    re.compile('['+_OPEN+r']\s*[^'+_CLOSE+r']{0,24}?教師備註[^'+_CLOSE+r']{0,12}['+_CLOSE+']'),
    re.compile(r'(?:後續原文|詳細內容|完整內容|其餘內容)?(?:請)?(?:詳|參)?見教師備註[。．.]?'),
    re.compile(r'教師備註'),
    re.compile(r'以下省略|以下略|下略|未完待續|（略）|\(略\)|〔略〕|\[略\]'),
    re.compile(r'\[待補\]|\[TODO\]|\bTODO\b|\bFIXME\b|lorem ipsum|【待補】|待補',re.IGNORECASE),
    re.compile(r'_x[0-9a-fA-F]{4}_'),
    re.compile(r'</?(?:br|p|div|span|b|i|u|strong|em)\s*/?>',re.IGNORECASE),
    re.compile(r'`{3}\w*'),
    re.compile(r'^#{1,6}\s+',re.MULTILINE),
]
_TRAILING_ELLIPSIS=re.compile(r'\s*(?:…+|⋯+|\.{3,}|。{2,}|、{2,})\s*$')
_LEADING_MARK=re.compile(r'^[ \t]*(?:[-*•●▪◦][ \t]+|\d+\)[ \t]+)',re.MULTILINE)
_CJK='\u4e00-\u9fff\u3000-\u303f\uff00-\uffef'
_CJK_GAP=re.compile('(?<=['+_CJK+r']) +(?=['+_CJK+'])')
# Detection patterns used by QA (anything still matching after cleaning is a defect).
RESIDUE_DETECT=[
    (re.compile(r'教師備註'),'出現「教師備註」字樣'),
    (re.compile(r'見備註|詳見備註'),'出現「見備註」字樣'),
    (re.compile(r'以下省略|以下略|下略|未完待續|（略）|\(略\)'),'出現省略字樣'),
    (re.compile(r'_x[0-9a-fA-F]{4}_'),'出現 Office 控制碼（如 _x000D_）'),
    (re.compile(r'(?:…|⋯|\.{3})\s*$'),'句尾被省略號截斷'),
    (re.compile(r'\[待補\]|\bTODO\b|\bFIXME\b|lorem ipsum|待補',re.IGNORECASE),'出現待補或佔位字'),
    (re.compile(r'</?[a-zA-Z][^>]*>'),'出現 HTML 標籤'),
    (re.compile(r'\*\*|^#{1,6}\s|`{3}',re.MULTILINE),'出現未處理的 Markdown 標記'),
    (re.compile(r'\\n|\\t'),'出現字面上的換行符號'),
    (re.compile(r'\b(?:undefined|null|NaN)\b'),'出現程式殘留字（undefined/null/NaN）'),
]

def strip_residue(value):
    """Remove generator residue from one student-visible string."""
    text=format_teaching_text(value)
    for pattern in _RESIDUE_SUBS:text=pattern.sub('',text)
    text=text.replace('**','').replace('\\n','\n')
    text=_LEADING_MARK.sub('',text)
    text=_CJK_GAP.sub('',text)
    text=re.sub(r'[ \t]{2,}',' ',text)
    text=re.sub(r'\n{3,}','\n\n',text)
    text='\n'.join(line.rstrip() for line in text.split('\n')).strip()
    return _TRAILING_ELLIPSIS.sub('',text)

def visible_strings(slide):
    """Yield (path, text) for every student-visible string of a slide (notes excluded)."""
    yield 'heading',slide.get('heading','')
    yield 'subheading',slide.get('subheading','')
    body=slide.get('body') or {}
    for i,t in enumerate(body.get('bullets') or []):yield f'body.bullets[{i}]',t
    for i,c in enumerate(body.get('columns') or []):
        yield f'body.columns[{i}].header',c.get('header','')
        for j,t in enumerate(c.get('points') or []):yield f'body.columns[{i}].points[{j}]',t
    for k in ('question','answer'):yield f'body.{k}',body.get(k,'')
    for i,m in enumerate(slide.get('modules') or []):
        yield f'modules[{i}].keyword',m.get('keyword','')
        yield f'modules[{i}].description',m.get('description','')
    for k in ('hint','key_sentence','answer_area'):
        if slide.get(k):yield k,slide[k]

def _clean_visible(slide):
    slide['heading']=strip_residue(slide.get('heading',''))
    if 'subheading' in slide:slide['subheading']=strip_residue(slide.get('subheading',''))
    body=slide.get('body')
    if slide.get('quiz'):
        for question in slide['quiz'].get('questions',[]):question['question']=strip_residue(question['question'])
        for answer in slide['quiz'].get('answers',[]):answer['answer']=strip_residue(answer['answer'])
    if 'reading_context' in slide:slide['reading_context']=strip_residue(slide['reading_context'])
    if isinstance(body,dict):
        if 'bullets' in body:body['bullets']=[strip_residue(t) for t in body.get('bullets') or []]
        for c in (body.get('columns') or []):
            c['header']=strip_residue(c.get('header',''))
            c['points']=[strip_residue(t) for t in c.get('points') or []]
        for k in ('question','answer'):
            if k in body:body[k]=strip_residue(body[k])
    for m in slide.get('modules') or []:
        m['keyword']=strip_residue(m.get('keyword',''))
        m['description']=strip_residue(m.get('description',''))
    for k in ('hint','key_sentence'):
        if isinstance(slide.get(k),str):slide[k]=strip_residue(slide[k])
    for key in ('visual_model','fallback_visual_model'):
        model=slide.get(key)
        if isinstance(model,dict):_clean_model(model)
    return slide

def _clean_model(node):
    if isinstance(node,dict):
        for k,v in node.items():
            if isinstance(v,str) and k in ('label','example','note','root','left','right','title','caption','unit','text'):
                node[k]=strip_residue(v)
            else:_clean_model(v)
    elif isinstance(node,list):
        for v in node:_clean_model(v)

def clean_slide_text(value):
    """Repair escapes everywhere and strip residue from student-visible slide fields."""
    if isinstance(value, str):
        return format_teaching_text(value)
    if isinstance(value, list):
        for index,item in enumerate(value):
            value[index]=clean_slide_text(item)
        return value
    if isinstance(value, dict):
        for key,item in value.items():
            value[key]=clean_slide_text(item)
        if 'heading' in value and 'body' in value:_clean_visible(value)
        return value
    return value
