"""單頁離線品質檢查。重大問題分為硬性失敗與可嘗試修復的 SOFT 類型。"""
import ast
import math
import re
from fractions import Fraction
from .design import route,split_answer
from .text_safety import RESIDUE_DETECT,visible_strings
from .visuals import model_numbers,model_text

SOFT={'too_long','wall_of_text','no_visual','no_task','no_example','long_sentence','no_ratio_unit'}
# Presentation-only problems: the drafted teaching content is usable, so a page that still fails on
# these alone is kept for the teacher to confirm instead of being replaced by raw source text.
KEEPABLE={'ghost_image','truncated','bad_break','untraceable','hook_dense'}
# 'untraceable' alone means every equation checked out but one number's origin is unclear. Keeping the
# drafted page with a 【待教師確認】 note is far more useful than a blank teacher-prompt page; wrong
# arithmetic ('arithmetic'), copied text and fake context remain hard failures.
# Compound terms that contain an object character (尺, 筆, 茶) but do not name that object.
NON_OBJECT_TERMS=('比例尺','縮尺','尺規','尺度','尺寸','筆畫','筆劃','筆順','筆記','筆者','茶葉')
ANSWER_LABEL_WORDS=('答案','作答','算式','列式','計算','結果','單位','說明','理由','過程','答')

FRUITS=('蘋果','橘子','柳橙','香蕉','葡萄','西瓜','草莓','芒果','鳳梨','水梨','檸檬','桃子','櫻桃','番茄','柚子')
STATIONERY=('鉛筆','原子筆','紅筆','藍筆','黑筆','橡皮擦','橡皮','尺','筆記本','色筆','彩色筆','貼紙','橡皮筋','立可帶','筆')
DRINKS=('紅茶','綠茶','奶茶','果汁','檸檬汁','柳橙汁','鮮奶','牛奶','豆漿','汽水','咖啡','飲料','茶')
FOODS=('餅乾','蛋糕','麵粉','砂糖','雞蛋','奶油','巧克力','糖果','麵包','布丁','香蕉','蘋果','牛奶','鮮奶','檸檬','紅茶')
TOYS=('玩偶','積木','彈珠','氣球','卡片','玩具','公仔')
OBJECTS=tuple(sorted(set(FRUITS+STATIONERY+DRINKS+FOODS+TOYS+('點數','顏料','水彩','油漆','清水','白糖','美元','新臺幣','新台幣','男生','女生','紅球','藍球','白球')),key=len,reverse=True))
ALIASES=[{'橘子','柳橙'},{'鮮奶','牛奶'},{'玩偶','玩具','公仔'},{'美元','美金'},{'新臺幣','新台幣','臺幣','台幣'},
         {'紅茶','茶'},{'原子筆','筆'},{'橡皮','橡皮擦'},{'檸檬','檸檬汁'},{'果汁','柳橙汁','檸檬汁'},{'糖','砂糖','白糖'}]
CATEGORIES={'水果攤':FRUITS,'水果店':FRUITS,'水果':FRUITS,'果園':FRUITS,'文具店':STATIONERY,'文具':STATIONERY,
            '飲料店':DRINKS,'飲料':DRINKS,'點心':FOODS,'烘焙':FOODS,'蛋糕店':FOODS,'食譜':FOODS,'玩具店':TOYS,'玩具':TOYS}
EN_ZH={'lemon':'檸檬','tea':'茶','milk':'奶','apple':'蘋果','orange':'橘','banana':'香蕉','flour':'麵粉','sugar':'糖',
       'pencil':'筆','pen':'筆','eraser':'橡皮','toy':'玩','doll':'玩偶','coin':'元','money':'元','cookie':'餅乾',
       'cake':'蛋糕','juice':'汁','grape':'葡萄','watermelon':'西瓜','strawberry':'草莓','candy':'糖','ball':'球',
       'block':'積木','card':'卡'}
DEFINITION=re.compile(r'是指|指的是|叫做|叫作|稱為|定義為|定義是|的定義')
GRADE_CHARS={4:80,5:80,6:80,7:110,8:110,9:110}
GRADE_SENTENCE={4:15,5:18,6:20,7:25,8:25,9:28}
DANGLING=tuple('的和與及並而但是把在就都也又或從向讓被將跟')
NUMBER=r'(?<![0-9])\d+(?:,\d{3})*(?:\.\d+)?(?![0-9])'
RESULT_CUE=re.compile(r'(?:[=＝→]|答|得|共|是|為|約|剩|等於|變成|成為)\s*[：:]?\s*[+\-−－]?\s*$')

def finding(code,message,severity='major',field=''):
    return {'code':code,'severity':severity,'message':message,'field':field}

def num(text):return Fraction(text.replace(',',''))
def numbers(text):return [num(m) for m in re.findall(NUMBER,text)]
def chars(text):return len(re.sub(r'[\s\W_]','',text or '',flags=re.UNICODE))
def hit(words,text):return [w for w in words if w in text]
def present(word,text):
    group=next((g for g in ALIASES if word in g),{word})
    return any(w in text for w in group)

def visible_fields(slide):
    return [(k,v) for k,v in visible_strings(slide) if isinstance(v,str) and v.strip()]

def other_text(slide,skip=()):
    """Everything a student sees except the heading (and skipped fields)."""
    parts=[v for k,v in visible_fields(slide) if k!='heading' and not any(k.startswith(s) for s in skip)]
    parts.append(model_text(slide.get('visual_model')))
    return '\n'.join(parts)


def is_blank_label(text):
    """True when the text ends in a short answer-blank label such as「最終答案（含單位）：」, not a cut sentence."""
    stripped=(text or '').rstrip()
    if not stripped or stripped[-1] not in '：:':return False
    lines=[l for l in stripped.splitlines() if l.strip()]
    last=lines[-1].strip()
    if len(last)>24 or re.search(r'[。！？!?]',last):return False
    return len(lines)>1 or any(word in last for word in ANSWER_LABEL_WORDS)

def check_residue(slide):
    out=[]
    for field,text in visible_fields(slide):
        from .source_reader import damaged_text
        if text.strip() and damaged_text(text):
            out.append(finding('source_encoding','文字含疑似 PDF 字型映射亂碼，請重新辨識來源頁面',field=field))
        from .source_reader import TEACHER_BLOCK,EDITOR_LINE
        if TEACHER_BLOCK.search(text) or EDITOR_LINE.search(text):
            out.append(finding('teacher_context_leak','教師用書側欄或編輯索引混入學生內容，請改寫成可作答的教學內容並把指引移到備註',field=field))
        for pattern,message in RESIDUE_DETECT:
            if pattern.search(text):out.append(finding('residue',f'{message}：「{text[:20]}」',field=field))
        stripped=text.rstrip()
        if field not in ('heading',) and not field.endswith('keyword') and chars(stripped)>=10:
            if not is_blank_label(stripped) and (stripped[-1] in '，、；：,;:' or (stripped[-1] in DANGLING and not re.search(r'[。！？!?）」』]$',stripped))):
                out.append(finding('truncated',f'句子似乎在中途被截斷：「…{stripped[-12:]}」',field=field))
        if re.search(r'(?m)^[，。、；：！？）」』]',text):
            out.append(finding('bad_break',f'換行位置錯誤，標點出現在行首：「{text[:20]}」','minor',field))
        if re.search(r'\d\n\d',text):out.append(finding('bad_break','數字被換行切開','minor',field))
        if any(text.count(a)!=text.count(b) for a,b in (('（','）'),('(',')'),('「','」'),('『','』'),('“','”'))) or text.count('"')%2:
            out.append(finding('truncated',f'括號或引號沒有成對：「{text[:20]}」','major' if field=='heading' else 'minor',field))
    return out


def evaluate(tokens):
    """tokens: [Fraction, op, Fraction, ...]; * and / bind tighter than + and -."""
    values=[tokens[0]];ops=[]
    for i in range(1,len(tokens),2):
        op,value=tokens[i],tokens[i+1]
        if op in '*/':
            if op=='/' and value==0:raise ZeroDivisionError
            values[-1]=values[-1]*value if op=='*' else values[-1]/value
        else:ops.append(op);values.append(value)
    total=values[0]
    for op,value in zip(ops,values[1:]):total=total+value if op=='+' else total-value
    return total

_ARITH_SIDE=r'[+\-−－]?\s*[0-9(（][0-9,. \t()+\-−－×÷*/（）]*'
EXPR=re.compile(r'(?<![0-9A-Za-z_.,:：()+\-−－×÷*/])('+_ARITH_SIDE+r')\s*[=＝]\s*('+_ARITH_SIDE+r')(?![0-9A-Za-z_.,/:：]|\s*又)')

def evaluate_expression(text):
    """Exact, bounded arithmetic; never execute model-provided code."""
    normalized=text.strip().translate(str.maketrans({'−':'-','－':'-','×':'*','÷':'/','（':'(', '）':')'})).replace(',','')
    tree=ast.parse(normalized,mode='eval')
    if len(list(ast.walk(tree)))>100:raise ValueError('算式過長')
    def visit(node):
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            return Fraction(ast.get_source_segment(normalized,node))
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=visit(node.operand);return -value if isinstance(node.op,ast.USub) else value
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult,ast.Div)):
            a,b=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Add):return a+b
            if isinstance(node.op,ast.Sub):return a-b
            if isinstance(node.op,ast.Mult):return a*b
            return a/b
        raise ValueError('非純數字算式')
    return visit(tree.body)
RATIO_EQ=re.compile('('+NUMBER+r')\s*[:：]\s*('+NUMBER+r')\s*[=＝]\s*('+NUMBER+r')\s*[:：]\s*('+NUMBER+')')
RATIO=re.compile('('+NUMBER+r')\s*[:：]\s*('+NUMBER+')')
VALUE=re.compile('('+NUMBER+r')\s*[:：]\s*('+NUMBER+r')\s*的?\s*比值\s*(?:是|為|＝|=)\s*('+NUMBER+r'(?:\s*/\s*'+NUMBER+r')?)')
GCD=re.compile('('+NUMBER+r')\s*(?:和|與|跟|、|及)\s*('+NUMBER+r')\s*的最大公因[數数]\s*(?:是|為|＝|=)\s*('+NUMBER+')')

def decimals(text):
    m=re.search(r'\.(\d+)',text);return len(m[1]) if m else 0

def check_arithmetic(text,field=''):
    out=[]
    for m in EXPR.finditer(text):
        expr,answer=m[1],m[2]
        if not re.search(r'[+\-−－×÷*/]',expr):continue
        try:
            value=evaluate_expression(expr);given=evaluate_expression(answer)
        except (ValueError,ZeroDivisionError,SyntaxError):continue
        if value==given:continue
        places=decimals(answer)
        approx=('約' in text[max(0,m.start()-4):m.start()] or '≈' in text[max(0,m.start()-2):m.start()])
        if places and abs(float(value)-float(given))<=0.5*10**-places+1e-9:continue
        if approx and abs(float(value)-float(given))<=abs(float(given))*0.02+.01:continue
        out.append(finding('arithmetic',f'算式不成立：{m[0].strip()}（正確是 {float(value):g}）',field=field))
    for m in RATIO_EQ.finditer(text):
        a,b,c,d=[num(x) for x in m.groups()]
        if b==0 or d==0 or a*d!=b*c:
            out.append(finding('arithmetic',f'比不相等：{m[0].strip()}',field=field))
            continue
        window=text[max(0,m.start()-25):m.end()+12]
        if '最簡' in window and c==int(c) and d==int(d) and math.gcd(int(c),int(d))!=1:
            out.append(finding('arithmetic',f'{m[3]}:{m[4]} 還不是最簡整數比',field=field))
    for m in VALUE.finditer(text):
        a,b=num(m[1]),num(m[2])
        if b==0:continue
        raw=m[3].replace(' ','')
        try:given=num(raw) if '/' not in raw else Fraction(raw.split('/')[0].replace(',',''))/Fraction(raw.split('/')[1].replace(',',''))
        except (ValueError,ZeroDivisionError):continue
        actual=a/b
        if actual!=given and not (decimals(raw) and abs(float(actual)-float(given))<=0.5*10**-decimals(raw)+1e-9):
            out.append(finding('arithmetic',f'比值不對：{m[1]}:{m[2]} 的比值應為 {float(actual):g}',field=field))
    for m in GCD.finditer(text):
        a,b,g=num(m[1]),num(m[2]),num(m[3])
        if a==int(a) and b==int(b) and math.gcd(int(a),int(b))!=g:
            out.append(finding('arithmetic',f'{m[1]} 和 {m[2]} 的最大公因數應為 {math.gcd(int(a),int(b))}',field=field))
    return out

def check_simplest(question,answer):
    """A 化成最簡整數比 question must end with the reduced ratio."""
    if '最簡' not in question:return []
    ratios=RATIO.findall(question) or re.findall(r'(\d+)\s*[^\d：:，。？]{0,4}[：:]\s*[^\d：:，。？]{0,6}?(\d+)',question)
    found=RATIO.findall(answer)
    if not ratios or not found:return []
    a,b=[num(x) for x in ratios[0]];c,d=[num(x) for x in found[-1]]
    if a!=int(a) or b!=int(b) or b==0:return []
    g=math.gcd(int(a),int(b));want=(Fraction(int(a),g),Fraction(int(b),g))
    if (c,d)!=want:
        return [finding('arithmetic',f'最簡整數比答案應為 {want[0]}:{want[1]}，卻寫成 {found[-1][0]}:{found[-1][1]}',field='body.answer')]
    return []


LABELS=re.compile(r'第\s*\d+\s*[步題頁個]|步驟\s*\d+|(?m:^\s*\d+\s*[.)）、]\s*)')
def _strip_labels(text):return LABELS.sub(' ',text)

def check_traceable(question_text,steps,field='steps'):
    """Every operand in the worked steps must come from the stated problem or an earlier step."""
    pool=set(numbers(_strip_labels(question_text)))|{Fraction(0),Fraction(1)}   # 0 and 1: long-division digits (補0, 個位記0)
    problems=[]
    for number_index,step in enumerate(steps):
        text=_strip_labels(step);local=set()
        for m in re.finditer(NUMBER,text):
            value=num(m[0]);before=text[max(0,m.start()-4):m.start()]
            is_result=bool(RESULT_CUE.search(before)) or bool(re.search(r'[=＝→]\s*[+\-−－]?\s*$',text[:m.start()]))
            if is_result:local.add(value);continue
            # Short division introduces a divisor derived from a known integer.
            # Only accept an exact divisor in an explicit division operation;
            # arithmetic validation still catches a wrong quotient.
            if re.search(r'[÷/]\s*$',text[:m.start()]) and value>1 and any(
                    known==int(known) and known>value and known%value==0 for known in pool|local):continue
            if value in pool or value in local or derivable(value,pool|local):continue
            # Digit-sum divisibility test (39 -> 3+9=12): a single digit taken from a known integer.
            if value==int(value) and 0<=value<=9 and re.search(r'[+＋]|位數|數字和',text) and any(
                    known==int(known) and known>=10 and str(int(value)) in str(int(known)) for known in pool|local):continue
            problems.append((number_index+1,m[0]))
        pool|=local|set(numbers(text))
    if problems:
        shown='、'.join(f'第{i}步的 {n}' for i,n in problems[:3])
        return [finding('untraceable',f'解題步驟中的數字找不到來源（題目或前一步）：{shown}。請在題目完整列出條件，並讓每個數字都能追溯。',field=field)]
    return []

def derivable(value,pool):
    """A divisor/factor that is the gcd of two known integers, or their exact quotient, is traceable.
    Moving the decimal point is traceable too: 10, 100, ... and any known number times or divided by a power
    of ten (0.3 ÷ 0.5 -> 3 ÷ 5 after multiplying both by 10)."""
    if value>0 and any(value==Fraction(10)**k for k in range(-4,5)):return True
    if value>0 and any(known>0 and value in (known*Fraction(10)**k for k in range(-4,5)) for known in pool):return True
    known=[n for n in pool if n==int(n) and n>0]
    # An exact divisor of a known integer is traceable: short-division divisors and quotients
    # (30÷2=15), prime factors (12=2×2×3), common factors. Wrong arithmetic is still caught by
    # check_arithmetic; an invented condition (a number that divides nothing given) still fails.
    if value==int(value) and value>1 and any(k>value and int(k)%int(value)==0 for k in known):return True
    for a in known:
        for b in known:
            if a!=b:
                if math.gcd(int(a),int(b))==value:return True
                if math.lcm(int(a),int(b))==value:return True
                if b!=0 and a/b==value:return True
    return False

def sentences(text):
    return [s.strip() for s in re.split(r'[。；;！!\n]+',text or '') if s.strip()]

def question_of(slide):
    body=slide.get('body') or {}
    return (body.get('question') or '').strip()

def problem_text(slide):
    body=slide.get('body') or {}
    return '\n'.join([question_of(slide),slide.get('subheading',''),*(body.get('bullets') or [])])

def step_list(slide):
    kind=route(slide['layout_id']);body=slide.get('body') or {}
    if kind=='Steps':
        mods=slide.get('modules') or []
        return [m['description'] for m in mods] if mods else sentences(body.get('code_snippet',{}).get('code',''))
    if kind=='Question':return sentences(body.get('answer',''))
    return []


def content_bigrams(text):
    text=re.sub(r'[^\u4e00-\u9fff]','',text or '')
    stop=('怎麼','怎樣','什麼','為什麼','猜猜看','想一想','動動手','練習一下','小挑戰','一起','祕密','秘密','來看','看看','多少','幾個','嗎','呢','的')
    for s in stop:text=text.replace(s,'|')
    return {seg[i:i+2] for seg in text.split('|') for i in range(len(seg)-1)}

def check_consistency(slide):
    out=[]
    heading=slide.get('heading','')+' '+(slide.get('subheading','') if route(slide['layout_id']) in ('Steps','Question') else '')
    body=other_text(slide)
    plain_heading=heading
    for term in NON_OBJECT_TERMS:plain_heading=plain_heading.replace(term,'')
    objects=[w for w in OBJECTS if w in plain_heading]
    objects=[w for w in objects if not any(w!=o and w in o for o in objects)]
    if objects and body.strip():
        missing=[w for w in objects if not present(w,body)]
        if missing and chars(body)>=6:
            found=[w for w in OBJECTS if w in body and not any(w!=o and w in o for o in OBJECTS if o in body)][:4]
            out.append(finding('mismatch',f'標題提到「{'、'.join(missing)}」，內容卻沒有出現（內容出現：{'、'.join(found) or '無'}）。標題、題目與圖解必須談同一件事。',field='heading'))
    elif body.strip() and chars(heading)>=4:
        h=content_bigrams(heading)
        if len(h)>=2 and not (h&content_bigrams(body)) and chars(body)>=12:
            out.append(finding('title_gap','標題與內容沒有共同的詞，請確認標題是否符合本頁內容','minor','heading'))
    # image keyword vs page text
    keyword=((slide.get('media_hint') or {}).get('search_keyword') or '').lower()
    visual=slide.get('visual_asset') or {}
    if keyword and visual.get('is_required'):
        page=heading+body
        zh=[EN_ZH[w] for w in re.findall(r'[a-z]+',keyword) if w in EN_ZH]
        if zh and not any(z in page for z in zh):
            out.append(finding('image_mismatch',f'圖片關鍵字「{keyword}」與頁面內容不符','minor','media_hint'))
    # picture words without a picture
    text=heading+body
    has_picture=bool(slide.get('visual_model') and slide['visual_model'].get('type') not in (None,'none')) or bool(visual.get('is_required'))
    if re.search(r'如圖|看圖|下圖|上圖|右圖|左圖|圖中',text) and not has_picture:
        out.append(finding('ghost_image','文字提到圖，但本頁沒有圖','major','body'))
    # numbers shown by the diagram must be used in the page text
    vm=slide.get('visual_model')
    if vm and vm.get('type') in ('icon_groups','bar_model','ratio_arrows'):
        shown=set(model_numbers(vm));page_numbers=set(numbers(text))|set(numbers(slide.get('speaker_notes','')))
        if shown and page_numbers and not (shown&page_numbers):
            out.append(finding('model_gap','圖解上的數字沒有出現在題目或說明中，圖文不一致','major','visual_model'))
    return out

def check_fake_context(slide):
    """A named scenario must really be used by the problem, otherwise it is decoration."""
    head=slide.get('heading','')+' '+slide.get('subheading','')
    problem=problem_text(slide)+'\n'+model_text(slide.get('visual_model'))+'\n'+(slide.get('body') or {}).get('answer','')
    if not re.search(r'\d',problem):return []
    for category,words in CATEGORIES.items():
        if category in head and not hit(words,problem):
            return [finding('fake_context',f'標題或情境提到「{category}」，但題目完全沒有用到相關物品（只是純數字題）。請改成真的用到該物品（例如「蘋果 6 顆：橘子 4 顆」），否則拿掉情境標題，標成「練習一下」。',field='heading')]
    return []

def autofix(slide):
    """Deterministic repair for a decorative scenario title; returns notes."""
    notes=[]
    if not slide.get('misconception'):
        def fraction_text(value):
            denominator=value.denominator
            for prime in (2,5):
                while denominator%prime==0:denominator//=prime
            if denominator==1:
                from decimal import Decimal,localcontext
                with localcontext() as ctx:
                    ctx.prec=40
                    return format(Decimal(value.numerator)/Decimal(value.denominator),'f').rstrip('0').rstrip('.') if value.denominator!=1 else str(value.numerator)
            return f'{value.numerator}/{value.denominator}'
        def correct(text):
            def ratio(match):
                a,b=num(match[1]),num(match[2])
                if b==0:return match[0]
                raw=match[3].replace(' ','')
                try:given=evaluate_expression(raw)
                except (ValueError,ZeroDivisionError,SyntaxError):return match[0]
                if given==a/b:return match[0]
                notes.append('已以精確分數計算修正比值：'+match[1]+':'+match[2])
                return match[0][:match.start(3)-match.start()]+fraction_text(a/b)
            def gcd(match):
                a,b=num(match[1]),num(match[2])
                if a!=int(a) or b!=int(b) or a<0 or b<0:return match[0]
                answer=math.gcd(int(a),int(b))
                if num(match[3])==answer:return match[0]
                notes.append('已以整數計算修正最大公因數')
                return match[0][:match.start(3)-match.start()]+str(answer)
            return GCD.sub(gcd,VALUE.sub(ratio,text))
        body=slide.get('body') or {}
        # Never rewrite source evidence or a question containing a deliberately
        # wrong option. Only affirmative worked results are calculator targets.
        for key in ('answer',):
            if body.get(key):body[key]=correct(body[key])
        body['bullets']=[correct(t) for t in body.get('bullets',[])]
        for module in slide.get('modules',[]):module['description']=correct(module['description'])
        for entry in (slide.get('quiz') or {}).get('answers',[]):entry['answer']=correct(entry['answer'])
    mismatched=check_consistency(slide)
    if any(f['code']=='mismatch' for f in mismatched):
        question=question_of(slide)
        named=[w for w in OBJECTS if w in question]
        named=[w for w in named if not any(w!=other and w in other for other in named)]
        missing=[w for w in OBJECTS if w in slide.get('heading','') and not present(w,question)]
        missing=[w for w in missing if not any(w!=other and w in other for other in missing)]
        if question and len(named)==1 and len(missing)==1:
            slide['heading']=slide['heading'].replace(missing[0],named[0])
            notes.append('標題情境已依完整題幹對齊：'+named[0])
    fake=check_fake_context(slide)
    if fake:
        slide['heading']='練習一下'
        if any(c in slide.get('subheading','') for c in CATEGORIES):slide['subheading']=''
        notes.append('裝飾性情境標題已改為「練習一下」')
    return notes


def final_of(slide):
    answer=((slide.get('body') or {}).get('answer') or '').strip()
    if not answer:return ''
    final=split_answer(answer)[1] or answer
    return re.sub(r'^(?:答|解答|答案)\s*[：:]?\s*','',final).strip('。 ')

def check_exposure(slide,item=None):
    out=[]
    kind=route(slide['layout_id']);stage=slide.get('stage')
    if stage=='answer':return out
    final=final_of(slide)
    exposed_fields=[('heading',slide.get('heading','')),('subheading',slide.get('subheading','')),
                    ('hint',slide.get('hint','')),('key_sentence',slide.get('key_sentence',''))]
    body=slide.get('body') or {}
    if kind=='Question':exposed_fields.append(('body.question',body.get('question','')))
    for field,text in exposed_fields:
        if not text:continue
        # "答：＿＿" is an empty answer line the student fills in; only a label followed by real content is a leak.
        if re.search(r'(?:^|[\s。，；])(?:答案|解答|答)\s*(?:[是為]|[：:]\s*[^\s_＿﹏—…。.\-－□▢])',text) and kind=='Question' and field!='key_sentence':
            out.append(finding('exposed_answer',f'題目頁不可提前出現答案字樣：「{text[:20]}」',field=field));continue
        if final and len(final)>=2 and (final in text) and not (stage=='steps'):
            if field=='body.question' and final in question_of(slide) and len(final)<=3:continue
            out.append(finding('exposed_answer',f'{field} 提前寫出答案「{final}」，應留到解答階段',field=field))
    misconception=(item or {}).get('misconception') or slide.get('misconception')
    if misconception:
        text=other_text(slide)
        if re.search(r'正確答案|答案是|答案為|應該選|正確的是',text):
            out.append(finding('exposed_answer','迷思判斷頁不可先公布正確答案，讓學生先投票或判斷','major','body'))
    return out

def check_hook(slide,item,concepts):
    out=[]
    if not item or 'student_task' not in item or item.get('phase')!='hook' or route(slide['layout_id']) in ('Cover','Section'):return out
    text=other_text(slide)+slide.get('heading','')
    if not re.search(r'[？?]',text):
        out.append(finding('hook_not_question','導入頁必須是一個學生 10 秒內能回答的問題（需有問句）',field='body.question'))
    if DEFINITION.search(text):
        out.append(finding('hook_definition','導入頁不可先顯示完整概念定義；先問問題，學生嘗試後才命名概念',field='body'))
    if chars(other_text(slide,skip=('modules',)))>90:
        out.append(finding('hook_dense','導入頁文字太多，應只留一個生活情境與一個問題',field='body'))
    front=' '.join(filter(None,[slide.get('heading',''),slide.get('subheading',''),question_of(slide)]))
    named=[c for c in concepts or [] if len(c)>=2 and c in front]
    if named:out.append(finding('hook_names_concept',f'導入題不該先講出概念名稱「{named[0]}」，等學生嘗試後再命名','minor','body.question'))
    return out


def check_teaching(slide,item,request):
    out=[];kind=route(slide['layout_id']);legacy=item is None or 'student_task' not in item
    body=slide.get('body') or {}
    if kind in ('Cover','Section'):return out
    if not legacy:
        if not (slide.get('student_task') or '').strip():
            out.append(finding('no_task','缺少「這頁要讓學生做什麼」(student_task)','major','student_task'))
        text=other_text(slide)
        vm=slide.get('visual_model');has_model=bool(vm and vm.get('type') not in (None,'none'))
        # The renderer draws real comparison and sequence cards from these
        # fields. Requiring a second visual_model wastes a content rewrite.
        columns=body.get('columns') or []
        native_compare=kind=='Two_Column' and len(columns)==2 and all(
            c.get('header','').strip() and any(str(p).strip() for p in c.get('points',[])) for c in columns)
        modules=slide.get('modules') or []
        native_steps=kind=='Steps' and bool(question_of(slide)) and len(modules)>=2 and all(
            m.get('keyword','').strip() and m.get('description','').strip() for m in modules)
        has_visual=has_model or native_compare or native_steps
        visual=slide.get('visual_asset') or {}
        needs=(item.get('phase') in ('concept','example') or item.get('misconception')) and kind not in ('Question','Summary')
        if needs and not has_visual and not visual.get('is_required'):
            severity='major' if (request or {}).get('subject')=='數學' else 'minor'
            out.append(finding('no_visual',f'{item.get("function") or item.get("phase")}頁需要圖解（visual_model）或有教學功能的圖片，不能只有文字','major' if severity=='major' else 'minor','visual_model'))
        if visual.get('is_required') and len((visual.get('reasoning') or '').strip())<4:
            out.append(finding('no_visual','插圖沒有說明教學用途，不能只當裝飾','minor','visual_asset'))
        if item.get('phase')=='concept' and kind in ('Text_Visual','Three_Cards') and not re.search(r'\d',text) and not has_model and (request or {}).get('subject')=='數學':
            out.append(finding('no_example','概念頁需要一個具體例子（含數字或圖解）','minor','body'))
        if (item.get('misconception') or slide.get('misconception')):
            options=native_compare or re.search(r'\bA[.．、:：)]|甲|選項',text) or (has_model and vm.get('type')=='compare_ab')
            if not options:
                out.append(finding('no_options','迷思頁需以 A/B 選項或左右對照讓學生判斷對錯','major','visual_model'))
    return out

def check_length(slide,request):
    out=[];grade=(request or {}).get('grade',6);limit=GRADE_CHARS.get(grade,90)
    kind=route(slide['layout_id']);body=slide.get('body') or {}
    if kind in ('Cover','Section'):return out
    if kind=='Question':
        parts=[body.get('question',''),slide.get('hint','')]
        total=sum(chars(p) for p in parts);cap=limit*1.2
    else:
        parts=[v for k,v in visible_fields(slide) if k not in ('heading',) and k!='body.answer']
        total=sum(chars(p) for p in parts);cap=limit*(1.6 if kind=='Steps' else 1.0)
    if total>cap*1.6:
        out.append(finding('wall_of_text',f'本頁可見文字約 {total} 字，遠超過此年級建議（約 {int(cap)} 字），請拆短或改成圖解',field='body'))
    elif total>cap:
        out.append(finding('too_long',f'本頁可見文字約 {total} 字，超過此年級建議約 {int(cap)} 字','minor','body'))
    for field,text in visible_fields(slide):
        if field=='heading':
            if len(text)>15:out.append(finding('too_long','標題超過 15 字','major','heading'))
            continue
        if chars(text)>80 and '\n' not in text:
            out.append(finding('wall_of_text',f'單段文字過長（{chars(text)} 字），不要把課本段落貼上來',field=field))
        else:
            per=GRADE_SENTENCE.get(grade,20)+8
            for s in sentences(text):
                if chars(s)>per and not re.search(r'[=＝÷×]',s):
                    out.append(finding('long_sentence',f'句子過長（{chars(s)} 字，此年級約 {per-8} 字內）：「{s[:14]}…」','minor',field));break
    return out


def check_copy(slide,sources):
    """A slide that repeats the cited textbook passages is rejected for a rewrite (originality.py)."""
    if not sources:return []
    from . import originality
    hits=[f for f in originality.check_slide_copy(slide,sources) if f['verdict']=='copied']
    if not hits:return []
    return [finding('verbatim_copy',originality.rewrite_advice(hits),'major',hits[0]['field'])]

def check_slide(slide,item=None,request=None,concepts=None,sources=None):
    """Return every finding for one slide (see module docstring)."""
    findings=[]
    findings+=check_residue(slide)
    if not (slide.get('misconception') or (item or {}).get('misconception')):
        # a misconception page deliberately shows a wrong statement for students to judge
        for field,text in visible_fields(slide):findings+=check_arithmetic(text,field)
        findings+=check_arithmetic((slide.get('body') or {}).get('answer',''),'body.answer')
    steps=step_list(slide)
    question=problem_text(slide)
    if steps and any(re.search(NUMBER,s) for s in steps):
        kind=route(slide['layout_id'])
        if kind=='Steps' and not question_of(slide):
            findings.append(finding('untraceable','例題頁必須完整寫出題目（body.question），步驟中的每個數字才有來源','major','body.question'))
        else:findings+=check_traceable(question,steps)
    if route(slide['layout_id'])=='Question':
        q=question_of(slide);a=(slide.get('body') or {}).get('answer','')
        findings+=check_simplest(q,a)
        if q and a and '=' in a.replace('＝','='):
            unused=[n for n in dict.fromkeys(numbers(q)) if n!=1 and n not in numbers(a)]
            if unused and len(numbers(q))>=2:
                findings.append(finding('unused_number',f'題目中的數字 {"、".join(str(int(n)) if n==int(n) else str(float(n)) for n in unused[:3])} 沒有在解答中使用','minor','body.answer'))
    findings+=check_consistency(slide)
    findings+=check_fake_context(slide)
    findings+=check_exposure(slide,item)
    findings+=check_hook(slide,item,concepts)
    findings+=check_teaching(slide,item,request)
    findings+=check_length(slide,request)
    findings+=check_copy(slide,sources)
    seen=set();unique=[]
    for f in findings:
        key=(f['code'],f['message'],f['field'])
        if key not in seen:seen.add(key);unique.append(f)
    return unique

def majors(findings):return [f for f in findings if f['severity']=='major']
def hard(findings):return [f for f in majors(findings) if f['code'] not in SOFT]
def soft(findings):return [f for f in majors(findings) if f['code'] in SOFT]
def keepable(findings):
    """Only presentation-level hard findings remain, so the drafted page is still worth keeping."""
    blocking=hard(findings)
    return bool(blocking) and all(f['code'] in KEEPABLE for f in blocking)

def feedback(findings):
    """Chinese repair instructions built from the findings."""
    lines=[f"- {f['message']}" + (f"（{f['field']}）" if f.get('field') else '') for f in findings if f['severity']=='major']
    if any(f['code']=='untraceable' for f in findings):
        lines.append('- 數值修復示例：題目給6與12，步驟可寫「6＋12＝18」，下一步才可用18。若原教材沒有18或推導，不能捏造「已知18」補進題目；應刪掉錯誤步驟並按原條件重算。')
    if any(f['code']=='mismatch' for f in findings):
        lines.append('- 先確定主教材與完整題幹中的對象，再生成標題；例如題幹是檸檬汁，就不能沿用紅茶標題。不得為符合標題而改動來源條件。')
    if any(f['code']=='ghost_image' for f in findings):
        lines.append('- 二選一修正：(1) 加入 visual_model（icon_groups、bar_model、ratio_arrows、compare_ab 或 concept_map），並讓文字與圖一致；(2) 刪掉「如圖、看圖、圖中、左邊／右邊的圖形」這類指向圖的說法，改成沒有圖也看得懂的敘述。')
    if any(f['code']=='truncated' for f in findings):
        lines.append('- 題目最後可以保留單獨一行的作答標籤（例如「答：」），其他句子必須完整結束，不能停在逗號、冒號或「的、和」等字。')
    if any(f['code']=='no_visual' for f in findings):
        lines.append('- 概念或例題頁請補上 visual_model（可畫的圖解），或寫成一個含數字的具體例子；不要只放文字。')
    return '本頁未通過教學品質檢查，請只修正下列問題並保留其他內容：\n'+'\n'.join(lines) if lines else ''

def summarize(pages):
    """pages: {number: {'passed':bool,'final':str,...}} -> small dict for result.json / UI."""
    failed=sorted(int(k) for k,v in pages.items() if v.get('final')=='fallback')
    warned=sorted(int(k) for k,v in pages.items() if v.get('final')=='warning')
    fixed=sorted(int(k) for k,v in pages.items() if v.get('final')=='regenerated')
    return {'pages':len(pages),'passed':sum(1 for v in pages.values() if v.get('passed')),
            'first_passed':sum(1 for v in pages.values() if v.get('passed') and v.get('final')=='passed'),
            'regenerated_pages':fixed,'warning_pages':warned,'fallback_pages':failed}

def render_findings(report):
    """Minor findings from the render layout report (font sizes)."""
    out={}
    for row in report or []:
        sizes=[s for s in row.get('font_sizes',[]) if isinstance(s,(int,float))]
        if sizes and min(sizes)<16:
            out[row['slide']]=[finding('render_font',f'第 {row["slide"]} 頁有字級 {min(sizes)}pt 小於 16pt','minor')]
    return out
