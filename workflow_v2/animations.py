"""以 PresentationML timing 設定點擊顯示答案；靜態匯出保留全部文字。"""
from pptx.oxml.xmlchemy import OxmlElement

def element(parent,name,**attrs):
    node=OxmlElement('p:'+name)
    for key,value in attrs.items():node.set(key,str(value))
    parent.append(node);return node

def appear_answers(slide,shapes):
    shapes=list(shapes)
    if not shapes:return
    timing=OxmlElement('p:timing');nodes=element(timing,'tnLst')
    root=element(element(nodes,'par'),'cTn',id=1,dur='indefinite',restart='never',nodeType='tmRoot')
    sequence=element(element(root,'childTnLst'),'seq',concurrent=1,nextAc='seek')
    main=element(sequence,'cTn',id=2,dur='indefinite',nodeType='mainSeq')
    group=element(element(element(main,'childTnLst'),'par'),'cTn',id=3,fill='hold')
    element(element(group,'stCondLst'),'cond',delay='indefinite')
    inner=element(element(element(group,'childTnLst'),'par'),'cTn',id=4,fill='hold')
    element(element(inner,'stCondLst'),'cond',delay=0)
    effects=element(inner,'childTnLst');next_id=5
    for shape in shapes:
        effect=element(element(effects,'par'),'cTn',id=next_id,presetID=1,presetClass='entr',
                       presetSubtype=0,fill='hold',nodeType='clickEffect' if next_id==5 else 'withEffect')
        element(element(effect,'stCondLst'),'cond',delay=0)
        behavior=element(element(element(effect,'childTnLst'),'set'),'cBhvr')
        node=element(behavior,'cTn',id=next_id+1,dur=1,fill='hold')
        element(element(node,'stCondLst'),'cond',delay=0)
        element(element(behavior,'tgtEl'),'spTgt',spid=shape.shape_id)
        element(element(behavior,'attrNameLst'),'attrName').text='style.visibility'
        element(element(behavior.getparent(),'to'),'strVal',val='visible')
        next_id+=2
    for direction in ('Prev','Next'):
        condition=element(element(sequence,direction.lower()+'CondLst'),'cond',evt='on'+direction,delay=0)
        element(element(condition,'tgtEl'),'sldTgt')
    builds=element(timing,'bldLst')
    for shape in shapes:element(builds,'bldP',spid=shape.shape_id,grpId=0,animBg=1)
    old=slide._element.find('{http://schemas.openxmlformats.org/presentationml/2006/main}timing')
    if old is not None:slide._element.remove(old)
    slide._element.insert_element_before(timing,'p:extLst')
