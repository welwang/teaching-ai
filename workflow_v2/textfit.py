"""Text measurement shared by the renderer and the visual-model drawing code."""
import math,unicodedata

class Overflow(ValueError):pass

def estimated_lines(text,width,font):
    capacity=max(1,width*72/font)
    return sum(max(1,math.ceil(sum(1 if unicodedata.east_asian_width(c) in 'WF' else .64 for c in line)/capacity)) for line in text.split('\n'))

def font_size(text,w,h,max_size=30,min_size=24):
    for size in range(max_size,min_size-1,-1):
        paragraphs=text.split('\n')
        needed=estimated_lines(text,max(.1,w-.25),size)*size*1.40+6*max(0,len(paragraphs)-1)
        if needed <= (h-.18)*72:return size
    raise Overflow('文字無法以學生可讀字級放入版面，請濃縮措辭、移除非必要說明至notes；保留完整題目、數據與答案。')

def fit_size(text,w,h,max_size,floor=12,pad=.1):
    """Largest size that fits a small shape; never raises (used for diagram labels)."""
    for size in range(max_size,floor-1,-1):
        if estimated_lines(text,max(.1,w-2*pad),size)*size*1.25<=max(.1,h-pad)*72:return size
    return floor
