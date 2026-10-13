"""合併訓練權重並匯入本機 Ollama，保留原模型的提示格式與參數。"""
import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

from .common import ROOT, RUNS

BASE_OLLAMA = 'qwen3.8:27b-q4_K_M'
HOST = '127.0.0.1:11435'


def model_name(run):
    tag = re.sub(r'[^a-z0-9]+', '-', run.lower()).strip('-')[-24:] or 'run'
    return f'qwen3.8:27b-teach-{tag}'


def modelfile(base_text, source):
    """The base model's Modelfile with every FROM line replaced by `source` (the new weights)."""
    lines = [line for line in base_text.splitlines() if not re.match(r'\s*FROM\s', line, re.I)]
    lines = [line for line in lines if not line.lstrip().startswith('#')]
    return f'FROM {source}\n' + '\n'.join(lines).strip() + '\n'


def ollama_binary():
    for path in (ROOT / 'runtime' / 'ollama' / 'ollama.exe', Path(os.getenv('LOCALAPPDATA', '')) / 'Programs' / 'Ollama' / 'ollama.exe'):
        if path.is_file():
            return str(path)
    saved = ROOT / 'logs' / 'ollama-binary.txt'
    if saved.is_file() and Path(saved.read_text(encoding='utf-8').strip()).is_file():
        return saved.read_text(encoding='utf-8').strip()
    found = shutil.which('ollama')
    if found:
        return found
    raise SystemExit('找不到 Ollama 執行檔；請先開啟教材AI一次（它會啟動模型服務）')


def ollama(*args, check=True):
    env = dict(os.environ, OLLAMA_HOST=HOST, OLLAMA_MODELS=str(ROOT / 'models' / 'ollama'))
    done = subprocess.run([ollama_binary(), *args], env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and done.returncode:
        raise RuntimeError((done.stderr or done.stdout).strip()[-800:])
    return done.stdout


def largest_gguf(folder):
    files = [p for p in Path(folder).rglob('*.gguf') if 'mmproj' not in p.name.lower()]
    return max(files, key=lambda p: p.stat().st_size) if files else None


def main(argv=None):
    parser = argparse.ArgumentParser(description='把訓練結果匯入教材ai的 Ollama')
    parser.add_argument('run', help='訓練名稱（data\\distill\\runs 底下的資料夾）')
    parser.add_argument('--quant', default='q4_k_m')
    args = parser.parse_args(argv)
    run = RUNS / args.run
    if not (run / 'adapter').is_dir():
        raise SystemExit(f'找不到 {run / "adapter"}；請確認訓練已完成')
    name = model_name(args.run)
    base_text = ollama('show', '--modelfile', BASE_OLLAMA)
    from unsloth import FastModel
    model, processor = FastModel.from_pretrained(model_name=str(run / 'adapter'), load_in_4bit=True)
    tokenizer = getattr(processor, 'tokenizer', processor)
    source, quantize = None, []
    try:
        print('匯出 GGUF（合併權重後量化，約需 20～60 分鐘與 60 GB 以上的磁碟空間）…')
        model.save_pretrained_gguf(str(run / 'gguf'), tokenizer, quantization_method=args.quant)
        source = largest_gguf(run / 'gguf')
        if source is None:
            raise RuntimeError('沒有產生 GGUF 檔')
    except Exception as exc:  # noqa: BLE001 - fall back to letting Ollama quantize merged weights
        print('GGUF 匯出沒有成功，改用合併後的權重讓 Ollama 量化：' + str(exc)[:200])
        model.save_pretrained_merged(str(run / 'merged'), tokenizer, save_method='merged_16bit')
        source, quantize = run / 'merged', ['--quantize', 'q4_K_M']
    (run / 'Modelfile').write_text(modelfile(base_text, source), encoding='utf-8')
    print(f'建立 Ollama 模型 {name} …')
    ollama('create', name, '-f', str(run / 'Modelfile'), *quantize)
    (run / 'ollama-name.txt').write_text(name, encoding='utf-8')
    print(f'完成：{name}\n下一步：7-比較新舊.cmd {name}（比較完再決定要不要在 config.yaml 設 distilled_model）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
