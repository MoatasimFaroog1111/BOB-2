"""Deterministic seed examples for offline model training.

No Odoo credentials, amounts, or private identifiers are required. Real
organization examples can later be appended after human labeling.
"""

from __future__ import annotations

import random

NAME_VARIANT_GROUPS: dict[str, list[str]] = {
    "غلام": ["غلام", "Ghulam", "Gulam", "Gholam", "Ghulaam", "Golam"],
    "محمد": ["محمد", "Mohammed", "Muhammad", "Mohamed", "Mohammad", "Mohamad"],
    "عبدالله": ["عبدالله", "عبد الله", "Abdullah", "Abdallah", "Abdulla"],
    "احمد": ["أحمد", "احمد", "Ahmed", "Ahmad", "Ahamed"],
    "محمود": ["محمود", "Mahmoud", "Mahmud", "Mahmood"],
    "يوسف": ["يوسف", "Yousef", "Yusuf", "Youssef"],
    "ابراهيم": ["إبراهيم", "ابراهيم", "Ibrahim", "Ebrahim"],
    "خالد": ["خالد", "Khaled", "Khalid"],
    "عبدالرحمن": ["عبدالرحمن", "عبد الرحمن", "Abdulrahman", "Abdelrahman", "Abdurrahman"],
    "عثمان": ["عثمان", "Othman", "Osman", "Uthman"],
    "حسين": ["حسين", "Hussain", "Hussein", "Husain"],
    "حسن": ["حسن", "Hasan", "Hassan"],
    "مصطفي": ["مصطفى", "مصطفي", "Mostafa", "Mustafa"],
    "طارق": ["طارق", "Tariq", "Tarek"],
    "علي": ["علي", "Ali", "Aly"],
    "عمر": ["عمر", "Omar", "Umar"],
    "سليمان": ["سليمان", "Sulaiman", "Suleiman", "Soliman"],
    "صالح": ["صالح", "Saleh", "Salih"],
    "ناصر": ["ناصر", "Nasser", "Nasir"],
    "عبدالعزيز": ["عبدالعزيز", "عبد العزيز", "Abdulaziz", "Abdelaziz"],
    "بشير": ["بشير", "Bashir", "Basheer"],
    "معتصم": ["معتصم", "Moatasim", "Mutasim", "Motasem"],
    "هلا": ["هلا", "Hala", "Halaa"],
    "هشام": ["هشام", "Hisham", "Hesham"],
    "جميل": ["جميل", "Jameel", "Jamil"],
    "جمال": ["جمال", "Jamal", "Gamal"],
    "غاده": ["غادة", "غاده", "Ghada", "Gada"],
    "فاطمه": ["فاطمة", "فاطمه", "Fatima", "Fatma"],
    "نور": ["نور", "Noor", "Nour"],
    "وليد": ["وليد", "Waleed", "Walid"],
    "شعبان": ["شعبان", "Shaban", "Shaaban"],
    "رامي": ["رامي", "Rami", "Ramy"],
    "سعيد": ["سعيد", "Saeed", "Said"],
    "عبداللطيف": ["عبداللطيف", "عبد اللطيف", "Abdullatif", "Abdul Latif", "Abdel Latif"],
    "زكريا": ["زكريا", "Zakaria", "Zakariya", "Zachariah"],
    "طلال": ["طلال", "Talal"],
    "منصور": ["منصور", "Mansour", "Mansur"],
    "رشا": ["رشا", "Rasha"],
    "غيث": ["غيث", "Ghaith", "Gaith"],
    "سالم": ["سالم", "Salem", "Salim"],
    "مازن": ["مازن", "Mazen", "Mazin"],
    "رائد": ["رائد", "Raed", "Rayed"],
    "نادر": ["نادر", "Nader", "Nadir"],
    "سامر": ["سامر", "Samer"],
    "عماد": ["عماد", "Emad", "Imad"],
    "عادل": ["عادل", "Adel", "Adil"],
    "فيصل": ["فيصل", "Faisal", "Faysal"],
    "فهد": ["فهد", "Fahad", "Fahd"],
    "سامي": ["سامي", "Sami", "Samy"],
    "عبدالمجيد": ["عبدالمجيد", "عبد المجيد", "Abdulmajeed", "Abdel Majeed", "Abdul Majid"],
}

POSITIVE_CONTEXTS = [
    "{}",
    "شركة {}",
    "مؤسسة {} التجارية",
    "دفعة إلى {}",
    "شيك باسم {}",
    "Payment to {}",
    "Petty cash - {}",
    "Cheque for {}",
    "{} Trading Est.",
    "{}: 31978",
    "Vendor {}",
    "Partner {}",
    "تحويل إلى {}",
]

HARD_NEGATIVES: list[tuple[str, str]] = [
    ("غلام", "شركة هلا السعودية للخدمات البترولية: 31978"),
    ("غلام", "هلا"),
    ("غلام", "Hala"),
    ("غلام", "Ghada"),
    ("غلام", "غادة"),
    ("غلام", "Petty cash-Mohamed Ahmed Shaban Ali"),
    ("غلام", "Other Receivable"),
    ("غلام", "31978"),
    ("محمد", "محمود"),
    ("محمد", "Mahmoud"),
    ("احمد", "حمد"),
    ("احمد", "Hamad"),
    ("عبدالله", "عبيد الله"),
    ("عبدالله", "Abidullah"),
    ("علي", "عالي"),
    ("عمر", "عمرو"),
    ("جمال", "جميل"),
    ("جميل", "جمال"),
    ("طلال", "Tala"),
    ("طلال", "تالا"),
    ("رشا", "Rashad"),
    ("رشا", "رشاد"),
    ("بشير", "Bashar"),
    ("ناصر", "Nasra"),
    ("سالم", "Salma"),
    ("سعيد", "Saad"),
    ("رامي", "Ramez"),
    ("غيث", "Ghada"),
    ("زكريا", "Zikri"),
    ("منصور", "Nasser"),
    ("خالد", "Kholoud"),
    ("حسين", "Hasan"),
    ("حسين", "Hassan"),
    ("حسن", "Hussain"),
    ("حسن", "Hussein"),
    ("فاطمه", "Fahad"),
    ("نور", "Noura"),
    ("هشام", "Shaban"),
    ("سامي", "Samer"),
    ("سامر", "Sami"),
    ("مازن", "Mazinah"),
    ("نادر", "Nadia"),
]

RANDOM_SEED = 20260729


def build_training_examples() -> list[tuple[str, str, int]]:
    examples: list[tuple[str, str, int]] = []

    for variants in NAME_VARIANT_GROUPS.values():
        queries = [variants[0]]
        if len(variants) > 1:
            queries.append(variants[1])

        for query in queries:
            for variant in variants:
                for context in POSITIVE_CONTEXTS:
                    examples.append((query, context.format(variant), 1))

    generator = random.Random(RANDOM_SEED)
    group_names = list(NAME_VARIANT_GROUPS)

    for group_name, variants in NAME_VARIANT_GROUPS.items():
        query = variants[0]
        other_groups = [name for name in group_names if name != group_name]
        generator.shuffle(other_groups)

        for other_group in other_groups[:18]:
            candidate = generator.choice(NAME_VARIANT_GROUPS[other_group])
            random_context = generator.choice(POSITIVE_CONTEXTS)
            examples.append((query, random_context.format(candidate), 0))
            examples.append((query, candidate, 0))

    for query, candidate in HARD_NEGATIVES:
        for context in (
            "{}",
            "شركة {}",
            "Payment to {}",
            "Petty cash - {}",
            "{} Trading Est.",
        ):
            examples.append((query, context.format(candidate), 0))

    deduplicated: dict[tuple[str, str], int] = {}

    for query, candidate, label in examples:
        key = (query, candidate)
        previous = deduplicated.get(key)

        if previous is not None and previous != label:
            raise RuntimeError(f"Conflicting training label for {key!r}.")

        deduplicated[key] = label

    return [
        (query, candidate, label)
        for (query, candidate), label in deduplicated.items()
    ]


def validation_examples() -> list[tuple[str, str, int]]:
    return [
        ("غلام", "Ghulam", 1),
        ("غلام", "Gulam Trading Est.", 1),
        ("غلام", "Gholam", 1),
        ("غلام", "دفعة إلى غلام محمد", 1),
        (
            "غلام",
            "شركة هلا السعودية للخدمات البترولية: 31978",
            0,
        ),
        ("غلام", "Hala", 0),
        ("غلام", "Other Receivable", 0),
        ("محمد", "Mohammed Ahmed", 1),
        ("محمد", "محمود", 0),
        ("احمد", "حمد", 0),
        ("عبدالله", "Abdullah Contracting", 1),
        ("عبدالله", "عبيد الله", 0),
        ("يوسف", "Youssef Trading", 1),
        ("عبداللطيف", "Abdul Latif Trading", 1),
        ("طلال", "Talal", 1),
        ("طلال", "Tala Trading", 0),
        ("رشا", "Rasha", 1),
        ("رشا", "Rashad", 0),
        ("غيث", "Ghaith Trading", 1),
        ("حسن", "Hussain", 0),
        ("حسين", "Hassan", 0),
    ]
