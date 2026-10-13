"""Hand-written 「比和比值」 deck that exercises every v3 teaching feature (no model needed)."""
from workflow_v2.contracts import VISUAL_STYLE

NO_ASSET={'is_required':False,'reasoning':'以圖解呈現，不需照片','asset_type':'none','image_prompt':'','style_tags':VISUAL_STYLE}

def make(layout,heading,role,task,subheading='',bullets=None,question='',answer='',modules=None,columns=None,notes='',**extra):
    slide={'layout_id':layout,'heading':heading,'subheading':subheading,
        'body':{'bullets':bullets or [],'columns':columns or [],'question':question,'answer':answer,
                'code_snippet':{'language':'','code':''}},
        'modules':modules or [],'visual_asset':dict(NO_ASSET),
        'media_hint':{'search_keyword':'','image_description':''},
        'speaker_notes':notes or '預估講解 40 秒。教師提問：先請學生回答，再說明。',
        'source_pages':[1],'page_role':role,'student_task':task}
    slide.update(extra)
    return slide

def sample_deck(template_id='g6-math-diagram'):
    slides=[
      make('Question','換美元怎麼換？','情境頁','10 秒內回答 64 元能換幾美元',
           question='32 元可以換 1 美元，那 64 元可以換幾美元？',answer='64÷32=2。答：2 美元。',
           hint='64 是 32 的幾倍？',think_seconds=10,
           visual_model={'type':'ratio_arrows','title':'','from':[32,1],'to':[64,2],'op':'×2','labels':['新臺幣','美元'],'units':['元','美元']},
           notes='導入：請學生先回答。答案 2 美元後，寫出 32:1 和 64:2，再命名這種寫法叫做「比」。'),
      make('Text_Visual','點數換玩偶','概念頁','數一數，說出 10 點換幾隻玩偶',subheading='10 點可以換 3 隻玩偶',
           bullets=['集滿 10 點，換 3 隻玩偶。'],modules=[{'keyword':'比','description':'10 點：3 隻，前項是點數'}],
           visual_model={'type':'icon_groups','title':'10 點換 3 隻','groups':[{'label':'點數','icon':'star','count':10},{'label':'玩偶','icon':'heart','count':3}]},
           key_sentence='比可以表示兩個量的關係'),
      make('Two_Column','哪一杯比較濃？','比較頁','判斷 A 和 B 誰的檸檬汁比較多',subheading='檸檬汁 2 匙配紅茶 5 杯，6 匙配 15 杯',
           columns=[{'header':'A','points':['2 匙：5 杯']},{'header':'B','points':['6 匙：15 杯']}],
           visual_model={'type':'compare_ab','title':'','left':{'title':'A 招牌配方','items':['檸檬汁 2 匙','紅茶 5 杯'],'value':'2 : 5'},
                         'right':{'title':'B 丹丹調的','items':['檸檬汁 6 匙','紅茶 15 杯'],'value':'6 : 15'}}),
      make('Text_Visual','2:5 和 6:15','概念頁','看箭頭，說出兩邊都乘幾',subheading='兩邊同時乘同一個數',
           bullets=['檸檬汁和紅茶都乘 3。'],modules=[{'keyword':'相等的比','description':'2:5 和 6:15 相等'}],
           visual_model={'type':'ratio_arrows','title':'','from':[2,5],'to':[6,15],'op':'×3','labels':['檸檬汁','紅茶'],'units':['匙','杯']},
           key_sentence='前項和後項同時乘同一個數，比的關係不變'),
      make('Two_Column','丹丹的比較多嗎？','比較頁','投票：一樣或不一樣，說出理由',subheading='丹丹說：10 匙配 15 杯比較濃。你同意嗎？',
           columns=[{'header':'A 一樣','points':['2:5 = 10:15']},{'header':'B 不一樣','points':['2:5 ≠ 10:15']}],
           misconception=True,
           visual_model={'type':'compare_ab','title':'先投票，再說理由','left':{'title':'A 一樣','items':['2 匙：5 杯','10 匙：15 杯'],'value':'2:5 = 10:15？'},
                         'right':{'title':'B 不一樣','items':['2 乘 5 得 10','5 乘 3 得 15'],'value':'不是同一個數'}},
           notes='迷思：只看到檸檬汁變多就以為比較濃。請學生先投票，再用 ×5 對 ×3 說明。'),
      make('Steps','紅筆藍筆怎麼算？','步驟頁','跟著三步驟，自己說出每個數從哪來',
           question='紅筆和藍筆的數量比是 2：3。紅筆有 12 枝，藍筆有幾枝？',
           modules=[{'keyword':'記下比','description':'紅筆：藍筆＝2：3，紅筆是 12 枝'},
                    {'keyword':'找倍數','description':'12÷2＝6，紅筆是 2 的 6 倍'},
                    {'keyword':'算答案','description':'3×6＝18，藍筆有 18 枝'}],
           visual_model={'type':'ratio_arrows','title':'','from':[2,3],'to':[12,18],'op':'×6','labels':['紅筆','藍筆'],'units':['枝','枝']},
           key_sentence='比的兩項要乘（或除）同一個數'),
      make('Question','水果店的比','練習頁','自己先算，再看提示',
           question='蘋果 6 顆：橘子 4 顆，化成最簡整數比。',answer='6÷2=3；4÷2=2。答：3:2。',hint='6 和 4 都能被 2 整除',think_seconds=20,
           visual_model={'type':'icon_groups','title':'','groups':[{'label':'蘋果','icon':'circle','count':6},{'label':'橘子','icon':'triangle','count':4}]},
           key_sentence='最簡整數比：兩項的公因數只剩 1'),
      make('Question','食譜變簡單','練習頁','用份數模型算出麵粉要幾克',
           question='香蕉 5 份是 210 克，麵粉 3 份是幾克？',answer='210÷5=42；42×3=126。答：126 克。',hint='先求 1 份是幾克',think_seconds=20,
           visual_model={'type':'bar_model','title':'','bars':[{'label':'香蕉','parts':5,'unit_value':42,'total':210,'unit':'克'},{'label':'麵粉','parts':3,'unit_value':42,'unknown':True,'unit':'克'}]}),
      make('Question','比和比值','練習頁','算出比值並說明單位',
           question='小明買 3 支紅筆花 50 元。50 元：3 支，比值是多少？',answer='50÷3=16 又 2/3。答：每支約 16.7 元。',hint='前項 50 除以後項 3',think_seconds=20,
           visual_model={'type':'bar_model','title':'','bars':[{'label':'總價','parts':1,'total':50,'unit':'元'},{'label':'支數','parts':3,'unit':'支'}]}),
      make('Two_Column','最大公因數和公因數','比較頁','分辨公因數和最大公因數',subheading='6 和 9 有哪些共同的因數？',
           columns=[{'header':'公因數','points':['1、3']},{'header':'最大公因數','points':['3']}],
           visual_model={'type':'compare_ab','title':'','left':{'title':'公因數','items':['6：1 2 3 6','9：1 3 9'],'value':'1、3'},
                         'right':{'title':'最大公因數','items':['最大的那個'],'value':'3'}}),
      make('Question','再挑戰一題','練習頁','用比例箭頭補出空格',
           question='3:4 = 12:？，箭頭上要乘幾？',answer='3×4=12，所以 4×4=16。答：16。',hint='3 變 12，乘幾？',think_seconds=20,
           visual_model={'type':'ratio_arrows','title':'','from':[3,4],'to':[12,16],'op':'×4','labels':['前項','後項'],'units':[]}),
      make('Summary','我們學會了什麼？','總結頁','用概念圖說出今天的三個重點',subheading='比、相等的比、最簡整數比',
           bullets=['比：兩個量的關係'],
           question='8:12 的最簡整數比是多少？比值是多少？',answer='8÷4=2；12÷4=3。答：2:3，比值是 2/3。',
           visual_model={'type':'concept_map','title':'','root':'比','children':[
               {'label':'比','example':'32 : 1','note':'前項：後項'},
               {'label':'相等的比','example':'2:5 = 6:15','note':'同乘同一個數'},
               {'label':'最簡整數比','example':'6:4 = 3:2','note':'同除最大公因數'},
               {'label':'比值','example':'50 ÷ 3','note':'前項 ÷ 後項'}]},
           notes='出口題：8:12 的最簡整數比是 2:3，比值是 2/3。'),
    ]
    for s in slides:
        s.setdefault('visual_asset',dict(NO_ASSET))
    return {'schema_version':1,'deck_meta':{'title':'比和比值','subject':'數學','target_audience':'國小學童',
            'primary_color':'#6E5BA8','template_id':template_id},'slides':slides}
