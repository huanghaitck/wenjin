from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path


def distance(left: list[str] | str, right: list[str] | str) -> int:
    previous = list(range(len(right) + 1))
    for row, left_item in enumerate(left, start=1):
        current = [row]
        for column, right_item in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_item != right_item),
            ))
        previous = current
    return previous[-1]


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text).replace("“", '"').replace("”", '"').replace("’", "'")


def score(reference: str, prediction: str) -> dict[str, float | int | None]:
    reference = normalize_text(reference)
    prediction = normalize_text(prediction)
    reference_chars = re.sub(r"\s+", "", reference)
    prediction_chars = re.sub(r"\s+", "", prediction)
    reference_words = re.findall(r"\S+", re.sub(r"\s+", " ", reference).strip())
    prediction_words = re.findall(r"\S+", re.sub(r"\s+", " ", prediction).strip())
    char_errors = distance(reference_chars, prediction_chars)
    cjk_characters = sum("\u3400" <= character <= "\u9fff" for character in reference_chars)
    cjk_dominant = cjk_characters / max(1, len(reference_chars)) >= 0.2
    word_errors = None if cjk_dominant else distance(reference_words, prediction_words)
    result: dict[str, float | int | None] = {
        "reference_characters": len(reference_chars),
        "prediction_characters": len(prediction_chars),
        "character_errors": char_errors,
        "cer": round(char_errors / max(1, len(reference_chars)), 6),
        "reference_words": None if cjk_dominant else len(reference_words),
        "prediction_words": None if cjk_dominant else len(prediction_words),
        "word_errors": word_errors,
        "wer": None if cjk_dominant else round(word_errors / max(1, len(reference_words)), 6),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Score OCR text after Unicode and whitespace normalization")
    parser.add_argument("reference", type=Path)
    parser.add_argument("prediction", type=Path)
    args = parser.parse_args()
    result = score(
        args.reference.read_text(encoding="utf-8"),
        args.prediction.read_text(encoding="utf-8"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
