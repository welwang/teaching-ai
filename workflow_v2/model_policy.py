"""System-owned inference selection; requests never choose the model in fixed mode."""
import yaml
from .store import ROOT

DEFAULT_MODEL = 'qwen3.8:27b-q4_K_M'


def settings():
    return yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8')) or {}


def base_model(config=None):
    """The model as installed (keeps image reading for scanned pages and final screenshot checks)."""
    config = settings() if config is None else config
    return config.get('preferred_model') or DEFAULT_MODEL


def configured_model(config=None):
    """Text model for every stage: the self-distilled model when config.yaml names one, otherwise the base model."""
    config = settings() if config is None else config
    distilled = str(config.get('distilled_model') or '').strip()
    return distilled or base_model(config)


def model_for_images(model, config=None):
    """Calls with images always go to the base model: a fine-tuned copy may have lost its vision part."""
    config = settings() if config is None else config
    distilled = str(config.get('distilled_model') or '').strip()
    trained = (distilled and model == distilled) or '-teach-' in str(model or '')   # also while comparing (distill.evaluate)
    return base_model(config) if trained else model


def configured_context():
    """One bounded runner allocation for every stage; never infer it from text length."""
    value = settings().get('generation_context', 8192)
    if type(value) is not int or value not in (8192, 16384, 32768):
        raise ValueError('generation_context 僅允許 8192、16384 或 32768；不啟用 1M 上下文')
    return value


def bind(request):
    value = dict(request)
    config = settings()
    if config.get('model_selection') == 'fixed':
        model = configured_model(config)
        value.update(model=model, page_model=model)
    return value
