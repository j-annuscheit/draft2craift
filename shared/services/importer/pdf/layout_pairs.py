from __future__ import annotations

from collections import defaultdict

from .layout_types import (
    PageAssignmentMap,
    PageChoiceMap,
    PairKey,
    PairPagesMap,
    PairPrototypesMap,
    PairSamplesMap,
    RectsByPage,
)


def robust_quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    clipped_q = max(0.0, min(1.0, q))
    index = int(round(clipped_q * (len(ordered) - 1)))
    return ordered[index]


def select_page_choices(accepted) -> tuple[PageChoiceMap, PageChoiceMap]:
    page_header_choice: PageChoiceMap = {}
    page_footer_choice: PageChoiceMap = {}

    for key, occurrences in accepted.items():
        side = key[0]
        for occurrence in occurrences:
            page_index = int(occurrence["page"])
            bbox = occurrence["bbox"]
            if side == "top":
                margin = max(0.0, float(occurrence["y1"]) + 6.0)
                previous = page_header_choice.get(page_index)
                if previous is None or margin > previous[1]:
                    page_header_choice[page_index] = (key, margin, bbox)
            else:
                margin = max(0.0, float(occurrence["page_h"]) - float(occurrence["y0"]) + 6.0)
                previous = page_footer_choice.get(page_index)
                if previous is None or margin > previous[1]:
                    page_footer_choice[page_index] = (key, margin, bbox)

    return page_header_choice, page_footer_choice


def collect_pair_samples(
    n_pages: int,
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
) -> tuple[PairPagesMap, PairSamplesMap, PairSamplesMap]:
    pair_pages: PairPagesMap = defaultdict(list)
    pair_top_samples: PairSamplesMap = defaultdict(list)
    pair_bottom_samples: PairSamplesMap = defaultdict(list)

    for page_index in range(n_pages):
        header_entry = page_header_choice.get(page_index)
        footer_entry = page_footer_choice.get(page_index)
        header_key = header_entry[0] if header_entry else None
        footer_key = footer_entry[0] if footer_entry else None
        pair_key: PairKey = (header_key, footer_key)

        pair_pages[pair_key].append(page_index)
        pair_top_samples[pair_key].append(header_entry[1] if header_entry else 0.0)
        pair_bottom_samples[pair_key].append(footer_entry[1] if footer_entry else 0.0)

    return pair_pages, pair_top_samples, pair_bottom_samples


def select_pair_keys(
    pair_pages: PairPagesMap,
    pair_top_samples: PairSamplesMap,
    pair_bottom_samples: PairSamplesMap,
    max_pairs: int,
) -> list[PairKey]:
    all_pairs = list(pair_pages.keys())
    all_pairs.sort(
        key=lambda key: (
            len(pair_pages.get(key, [])),
            (1 if key[0] else 0) + (1 if key[1] else 0),
            robust_quantile(pair_top_samples.get(key, [0.0]), 0.50)
            + robust_quantile(pair_bottom_samples.get(key, [0.0]), 0.50),
        ),
        reverse=True,
    )

    selected_pair_keys = all_pairs[:max_pairs] if all_pairs else [(None, None)]
    non_empty_pairs = [key for key in all_pairs if key[0] is not None or key[1] is not None]
    if selected_pair_keys and selected_pair_keys[0] == (None, None) and non_empty_pairs:
        selected_pair_keys[0] = non_empty_pairs[0]
    return selected_pair_keys


def build_pair_prototypes(
    selected_pair_keys: list[PairKey],
    pair_top_samples: PairSamplesMap,
    pair_bottom_samples: PairSamplesMap,
) -> PairPrototypesMap:
    pair_prototypes: PairPrototypesMap = {}
    for key in selected_pair_keys:
        top_values = pair_top_samples.get(key, [0.0])
        bottom_values = pair_bottom_samples.get(key, [0.0])
        pair_prototypes[key] = (
            max(0.0, robust_quantile(top_values, 0.85)),
            max(0.0, robust_quantile(bottom_values, 0.85)),
        )
    return pair_prototypes


def pair_distance(
    page_index: int,
    pair_key: PairKey,
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
    pair_prototypes: PairPrototypesMap,
) -> float:
    header_entry = page_header_choice.get(page_index)
    footer_entry = page_footer_choice.get(page_index)
    raw_top = header_entry[1] if header_entry else 0.0
    raw_bottom = footer_entry[1] if footer_entry else 0.0
    proto_top, proto_bottom = pair_prototypes[pair_key]
    distance = abs(raw_top - proto_top) + abs(raw_bottom - proto_bottom)

    header_raw = header_entry[0] if header_entry else None
    footer_raw = footer_entry[0] if footer_entry else None
    header_proto, footer_proto = pair_key

    if header_raw and header_proto and header_raw != header_proto:
        distance += 22.0
    elif header_raw and not header_proto:
        distance += 28.0
    elif not header_raw and header_proto:
        distance += 10.0

    if footer_raw and footer_proto and footer_raw != footer_proto:
        distance += 22.0
    elif footer_raw and not footer_proto:
        distance += 28.0
    elif not footer_raw and footer_proto:
        distance += 10.0

    return distance


def assign_pages_to_pairs(
    n_pages: int,
    selected_pair_keys: list[PairKey],
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
    pair_prototypes: PairPrototypesMap,
) -> PageAssignmentMap:
    page_assignment: PageAssignmentMap = {}

    for page_index in range(n_pages):
        best = min(
            selected_pair_keys,
            key=lambda key: pair_distance(
                page_index,
                key,
                page_header_choice,
                page_footer_choice,
                pair_prototypes,
            ),
        )
        page_assignment[page_index] = best

    for page_index in range(1, n_pages - 1):
        left = page_assignment[page_index - 1]
        current = page_assignment[page_index]
        right = page_assignment[page_index + 1]
        if left == right and current != left:
            left_distance = pair_distance(
                page_index,
                left,
                page_header_choice,
                page_footer_choice,
                pair_prototypes,
            )
            current_distance = pair_distance(
                page_index,
                current,
                page_header_choice,
                page_footer_choice,
                pair_prototypes,
            )
            if left_distance <= current_distance + 6.0:
                page_assignment[page_index] = left

    return page_assignment


def build_margins_and_rects(
    n_pages: int,
    page_assignment: PageAssignmentMap,
    pair_prototypes: PairPrototypesMap,
    page_header_choice: PageChoiceMap,
    page_footer_choice: PageChoiceMap,
) -> tuple[dict[int, float], dict[int, float], RectsByPage, float, float]:
    top_by_page: dict[int, float] = {}
    bottom_by_page: dict[int, float] = {}
    hf_rects_by_page: RectsByPage = {}

    for page_index in range(n_pages):
        pair_key = page_assignment[page_index]
        pair_top, pair_bottom = pair_prototypes.get(pair_key, (0.0, 0.0))
        top_by_page[page_index] = pair_top
        bottom_by_page[page_index] = pair_bottom

        header_proto, footer_proto = pair_key
        page_rects = {"header": [], "footer": []}
        header_entry = page_header_choice.get(page_index)
        footer_entry = page_footer_choice.get(page_index)

        if header_entry and header_proto and header_entry[0] == header_proto:
            page_rects["header"].append(header_entry[2])
        if footer_entry and footer_proto and footer_entry[0] == footer_proto:
            page_rects["footer"].append(footer_entry[2])
        if page_rects["header"] or page_rects["footer"]:
            hf_rects_by_page[page_index] = page_rects

    top_margin = max(top_by_page.values(), default=0.0)
    bottom_margin = max(bottom_by_page.values(), default=0.0)
    return top_by_page, bottom_by_page, hf_rects_by_page, top_margin, bottom_margin
