"""切換蒸餾模型設定並保留其餘設定；--off 還原預設模型。"""
import re
import shutil
import sys
import time

from .common import ROOT

LINE = re.compile(r'(?m)^#?[ \t]*distilled_model:.*$')


def switch(text, name):
    line = f'distilled_model: {name}' if name else '# distilled_model: qwen3.8:27b-teach-run-YYYYMMDD-HHMM'
    if LINE.search(text):
        return LINE.sub(lambda _: line, text, count=1)
    return text.rstrip('\n') + '\n' + line + '\n'


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        raise SystemExit('用法：python -m distill.adopt <模型名稱> | --off')
    name = '' if argv[0] == '--off' else argv[0]
    if name and not name.startswith('qwen3.8:27b'):
        raise SystemExit('模型名稱要以 qwen3.8:27b 開頭')
    path = ROOT / 'config.yaml'
    shutil.copy2(path, path.with_name(f'config.yaml.bak-{time.strftime("%Y%m%d-%H%M%S")}-distill-adopt'))
    path.write_text(switch(path.read_text(encoding='utf-8'), name), encoding='utf-8')
    print(f'config.yaml：{"distilled_model: " + name if name else "已恢復原本的模型"}（重新開啟教材AI 後生效）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
