"""Deterministic mother-layout geometry, independent of model-generated content."""

def layout_boxes(name,style):
    # Younger readers receive larger type and more breathing room. The six
    # margins are intentionally stable within a deck and distinct by grade.
    grade=style['grade'];mode=style['style']
    x=.87+(grade-4)*.025;w=13.333-2*x
    if style.get('look')=='mission':
        x=.93;w=11.47
    top=1.74 if grade<=6 else 1.65
    gap=.34 if style['subject']=='英語' else .42 if style['subject']=='國語' else .30
    boxes={0:(x,.67,w,.82),1:(x,top,(w-gap)/2,4.86),
           2:(x+(w+gap)/2,top,(w-gap)/2,4.86)}
    if name=='Text_Visual':
        fraction={'story':.48,'diagram':.39,'practice':.55,'focus':.58}[mode]
        left=(w-gap)*fraction
        boxes.update({1:(x,top,left,4.86),2:(x+left+gap,top,w-left-gap,4.86)})
    elif name in ('Cover','Section') and style.get('look')=='mission':
        boxes={0:(x,1.6,w*.86,1.6),1:(x,3.4,9.7,2.35),2:(x,6.05,w,.82)}
    elif name in ('Cover','Section'):
        if mode=='story':boxes={0:(x,1.35,7.35,1.55),1:(x,3.18,7.35,2.15),2:(9.0,2.0,3.35,3.3)}
        elif mode=='diagram':boxes={0:(x,1.68,w,1.5),1:(x,3.55,8.1,1.8),2:(x,5.75,w,.8)}
        elif mode=='practice':boxes={0:(x,1.65,w,1.65),1:(x,3.6,w,1.6),2:(x,5.52,w,.94)}
        else:boxes={0:(x,2.0,w,1.45),1:(x,3.75,w,1.5),2:(x,5.63,w,.83)}
    elif name=='Two_Column' and mode=='focus':
        boxes.update({1:(x,top,w,2.18),2:(x,top+2.48,w,2.18)})
    elif name=='Summary':
        if mode=='focus':boxes.update({1:(x,2.0,w,2.42),2:(x,4.78,w,1.75)})
        elif mode=='diagram':boxes.update({1:(x,2.15,5.25,3.88),2:(x+5.68,2.15,w-5.68,3.88)})
        elif mode=='practice':boxes.update({1:(x,2.1,w,2.24),2:(x,4.77,w,1.6)})
        else:boxes.update({1:(x,1.95,w,2.6),2:(x,4.86,w,1.7)})
    elif name=='Question':boxes.update({1:(x,1.75,w,2.05),2:(x,4.1,w,2.45)})
    elif name in ('Three_Cards','Steps'):boxes.update({1:(x,1.8,w,4.7),2:(x,6.5,w,.15)})
    if name=='Section' and mode!='story':
        sx,sy,sw,sh=boxes[2];boxes[2]=(sx,sy,sw,max(sh,1.10))
    return boxes


def card_boxes(style,count=3):
    """Three families use columns; focus uses horizontal reading modules."""
    x=.93;w=11.47;gap=.24;mode=style['style']
    if mode=='focus':
        return [(x,1.86+i*1.51,w,1.27) for i in range(count)]
    width=(w-(count-1)*gap)/count
    offset=.30 if mode=='story' else 0
    return [(x+i*(width+gap),1.94+(offset if i==1 else 0),width,
             4.46-(offset if i==1 else 0)) for i in range(count)]


def mission_chrome(name,style,boxes):
    """國中任務控制風格：封面/章節頁是近黑滿版底，內頁只有細線；先列出的圖形在上層。"""
    x,w=.93,11.47
    if name in ('Cover','Section'):
        return [(x,1.3,.9,.05,style['dark_accent'],None),(x,5.9,w,.012,style['dark_line'],None),
                (0,0,13.333,7.5,style['dark'],None)]
    if name=='Two_Column':
        return [(*boxes[i],'FFFFFF',style['hairline']) for i in (1,2)]
    if name=='Summary':
        return [(*boxes[1],style['pale'],None)]
    return []


def chrome(name,style):
    """Native structural panels; no illustrative assets or model coordinates."""
    p,bg,pale=style['primary'],style['background'],style['pale']
    boxes=layout_boxes(name,style);mode=style['style'];shapes=[]
    if style.get('look')=='mission':return mission_chrome(name,style,boxes)
    if name in ('Cover','Section'):
        if mode=='story':shapes=[(8.55,.72,3.87,5.95,pale,None)]
        elif mode=='diagram':shapes=[(.93,.94,1.65,.13,p,None),(.93,5.53,11.47,.025,p,None)]
        elif mode=='practice':shapes=[(.93,1.37,11.47,2.20,pale,p),(.93,5.33,11.47,1.28,'FFFFFF',pale)]
        else:shapes=[(3.92,1.54,5.49,.035,p,None),(3.92,5.42,5.49,.035,p,None)]
    elif name=='Two_Column':
        shapes=[(*boxes[i],'FFFFFF',pale) for i in (1,2)]
    elif name=='Summary':
        shapes=[(*boxes[1],pale,None)] if mode in ('practice','diagram') else []
    return shapes
