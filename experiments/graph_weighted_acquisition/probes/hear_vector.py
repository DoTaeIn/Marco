"""A trial, 2026-11-25: a sentence vector model on the hearing side. Not part of the system.

The owner asked to try, once, what a token-based model does when it is only allowed to hear. The
model turns the question and each property's words (its word, other words for it, its plain
explanation) into vectors and puts the properties in order of nearness. It writes nothing and
chooses among the field's own properties only; what it picks is put to the user as a proposal
(answer._anchor), never answered.

The model is one that is already on this machine (no download): jhgan/ko-sroberta-multitask, a
Korean sentence encoder, read from the local cache with the network off.
"""
import os

os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

NAME = 'jhgan/ko-sroberta-multitask'


def load():
    import torch
    from transformers import AutoModel, AutoTokenizer
    tokenizer, encoder = AutoTokenizer.from_pretrained(NAME), AutoModel.from_pretrained(NAME).eval()

    def vectors(texts):
        with torch.no_grad():
            batch = tokenizer(texts, padding=True, truncation=True, return_tensors='pt')
            hidden, mask = encoder(**batch).last_hidden_state, batch['attention_mask'].unsqueeze(-1).float()
            mean = (hidden * mask).sum(1) / mask.sum(1)            # mean pooling, as the model was trained
            return torch.nn.functional.normalize(mean, dim=1)

    def hear(question, properties):
        """The properties, nearest first, each with its cosine to the question."""
        names = sorted(properties)
        if not names:
            return []
        scores = (vectors([question]) @ vectors([properties[n] for n in names]).T)[0].tolist()
        return sorted(zip(names, scores), key=lambda row: (-row[1], row[0]))

    return hear
