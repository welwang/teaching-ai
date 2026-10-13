"""以 QLoRA 訓練語言層，僅計算回覆部分的損失；使用獨立訓練環境。"""
import argparse
import json
import math
import time
from pathlib import Path

from .common import DATASET, RUNS, read_jsonl

BASE = 'unsloth/Qwen3.8-27B'


def render(tokenizer, row):
    """(prompt text, full text) exactly as the system talks to the model: thinking off, then the reply."""
    prompt = tokenizer.apply_chat_template(row['messages'][:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False)
    end = getattr(tokenizer, 'eos_token', None) or '<|im_end|>'
    return prompt, prompt + row['messages'][-1]['content'] + end


def tokenize(tokenizer, rows, max_seq):
    """input_ids / labels with the prompt masked (-100); rows longer than max_seq are dropped and counted."""
    kept, dropped, lengths = [], 0, []
    for row in rows:
        prompt, full = render(tokenizer, row)
        # Prompt and reply are tokenized separately, as at inference (prompt first, then generated tokens),
        # so the loss mask lines up exactly with the reply.
        prompt_ids = tokenizer(prompt, add_special_tokens=False)['input_ids']
        reply_ids = tokenizer(full[len(prompt):], add_special_tokens=False)['input_ids']
        ids = prompt_ids + reply_ids
        lengths.append(len(ids))
        if len(ids) > max_seq or not reply_ids:
            dropped += 1
            continue
        kept.append({'input_ids': ids, 'attention_mask': [1] * len(ids), 'labels': [-100] * len(prompt_ids) + reply_ids})
    return kept, dropped, lengths


def main(argv=None):
    parser = argparse.ArgumentParser(description='在 5090 上用 QLoRA 微調 27B')
    parser.add_argument('--base', default=BASE, help='可訓練的原始權重（Hugging Face 名稱或本機資料夾）')
    parser.add_argument('--name', default='run-' + time.strftime('%Y%m%d-%H%M'))
    parser.add_argument('--max-seq', type=int, default=8192)
    parser.add_argument('--epochs', type=float, default=2)
    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--rank', type=int, default=16)
    parser.add_argument('--accumulate', type=int, default=8)
    parser.add_argument('--check', action='store_true', help='只檢查資料格式與長度，不訓練')
    args = parser.parse_args(argv)

    train_rows, val_rows = read_jsonl(DATASET / 'train.jsonl'), read_jsonl(DATASET / 'val.jsonl')
    if not train_rows:
        raise SystemExit('找不到訓練資料，請先執行 3-建立資料集.cmd')
    from unsloth import FastModel   # imported first so its patches apply
    model, processor = FastModel.from_pretrained(model_name=args.base, max_seq_length=args.max_seq,
                                                 load_in_4bit=True, full_finetuning=False)
    tokenizer = getattr(processor, 'tokenizer', processor)
    train, dropped, lengths = tokenize(tokenizer, train_rows, args.max_seq)
    val, val_dropped, _ = tokenize(tokenizer, val_rows, args.max_seq)
    lengths.sort()
    print(f'訓練 {len(train)} 筆（{dropped} 筆超過 {args.max_seq} 詞元略過），驗證 {len(val)} 筆；'
          f'長度中位數 {lengths[len(lengths) // 2]}、最長 {lengths[-1]} 詞元。')
    if args.check:
        prompt, full = render(tokenizer, train_rows[0])
        print('--- 範例（提示詞結尾與回覆開頭）---')
        print(full[len(prompt) - 300:len(prompt) + 300])
        print('--- 請確認上面「回覆開頭」之前的格式，和 `ollama show --template qwen3.8:27b-q4_K_M` 關閉思考時一致 ---')
        return 0

    model = FastModel.get_peft_model(model, finetune_vision_layers=False, finetune_language_layers=True,
                                     finetune_attention_modules=True, finetune_mlp_modules=True,
                                     r=args.rank, lora_alpha=args.rank, lora_dropout=0, bias='none',
                                     random_state=3407, use_gradient_checkpointing='unsloth')
    from datasets import Dataset
    from transformers import DataCollatorForSeq2Seq, Trainer, TrainingArguments
    out = RUNS / args.name
    steps = math.ceil(len(train) * args.epochs / args.accumulate)
    trainer = Trainer(
        model=model,
        train_dataset=Dataset.from_list(train),
        eval_dataset=Dataset.from_list(val) if val else None,
        data_collator=DataCollatorForSeq2Seq(tokenizer, padding=True, label_pad_token_id=-100),
        args=TrainingArguments(
            output_dir=str(out / 'checkpoints'), per_device_train_batch_size=1, gradient_accumulation_steps=args.accumulate,
            num_train_epochs=args.epochs, learning_rate=args.lr, warmup_ratio=0.05, lr_scheduler_type='cosine',
            optim='adamw_8bit', weight_decay=0.01, bf16=True, logging_steps=5, save_steps=max(25, steps // 4),
            save_total_limit=2, eval_strategy='steps' if val else 'no', eval_steps=max(25, steps // 4),
            per_device_eval_batch_size=1, dataloader_num_workers=0, report_to='none', seed=3407,
            remove_unused_columns=False))
    print(f'開始訓練：{steps} 步，結果存在 {out}')
    result = trainer.train()
    model.save_pretrained(str(out / 'adapter'))
    processor.save_pretrained(str(out / 'adapter'))
    info = {'base': args.base, 'name': args.name, 'examples': len(train), 'dropped': dropped, 'val': len(val),
            'epochs': args.epochs, 'lr': args.lr, 'rank': args.rank, 'max_seq': args.max_seq,
            'train_loss': getattr(result, 'training_loss', None),
            'eval': trainer.evaluate() if val else None, 'finished': time.strftime('%Y-%m-%d %H:%M')}
    (out / 'run.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'完成。下一步：6-匯出到Ollama.cmd {args.name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
