"""
Independent screening decisions per reviewer, inter-rater agreement (Cohen's kappa) and consolidation rules.

An AI agent authenticating with its own token is simply another reviewer here: its decisions are recorded
under its user, a human can compare them, and the consolidated ``Article.status`` is set explicitly.
"""

from collections import Counter, defaultdict

from django.contrib.auth.models import User
from django.db import transaction

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import Article, StudyDecision
from parsifal.apps.reviews.services._common import check_length, get_child, get_children

STAGES = dict(StudyDecision.STAGES)
STATUSES = dict(Article.ARTICLE_STATUS)

RULE_UNANIMOUS = "unanimous"  # all reviewers agree
RULE_ANY_INCLUDE = "any_include"  # Petersen 5.1.2: passes to the next step if at least one reviewer includes
RULE_MAJORITY = "majority"  # strict majority among reviewers
RULES = (RULE_UNANIMOUS, RULE_ANY_INCLUDE, RULE_MAJORITY)


def _validate_stage(stage):
    if stage not in STAGES:
        raise ValidationError(f"stage must be one of {sorted(STAGES)}.", field="stage")
    return stage


def _validate_status(status):
    if status not in STATUSES:
        raise ValidationError(f"status must be one of {sorted(STATUSES)}.", field="status")
    return status


def record_decision(
    *, review, article_id, actor, status, stage=StudyDecision.TITLE_ABSTRACT, criteria_id=None, comments=""
):
    article = get_child(review.article_set, article_id, label="Article")
    criteria = None
    if criteria_id not in (None, ""):
        criteria = get_child(review.selectioncriteria_set, criteria_id, label="Selection criteria")
    check_length(comments or "", 2000, field="comments")
    decision, _created = StudyDecision.objects.update_or_create(
        article=article,
        user=actor,
        stage=_validate_stage(stage),
        defaults={
            "review": review,
            "status": _validate_status(status),
            "selection_criteria": criteria,
            "comments": comments or "",
        },
    )
    return decision


def record_decisions(
    *, review, article_ids, actor, status, stage=StudyDecision.TITLE_ABSTRACT, criteria_id=None, comments=""
):
    articles = get_children(review.article_set, article_ids, label="Article")
    return [
        record_decision(
            review=review,
            article_id=a.pk,
            actor=actor,
            status=status,
            stage=stage,
            criteria_id=criteria_id,
            comments=comments,
        )
        for a in articles
    ]


def remove_decision(*, review, article_id, actor, stage=StudyDecision.TITLE_ABSTRACT):
    article = get_child(review.article_set, article_id, label="Article")
    deleted, _ = StudyDecision.objects.filter(article=article, user=actor, stage=_validate_stage(stage)).delete()
    if not deleted:
        raise NotFound("No decision of yours to remove for this article and stage.")


def list_decisions(review, *, stage=None, user_id=None, article_id=None, status=None):
    queryset = review.decisions.select_related("user", "selection_criteria", "article")
    if stage is not None:
        queryset = queryset.filter(stage=_validate_stage(stage))
    if user_id is not None:
        queryset = queryset.filter(user_id=user_id)
    if article_id is not None:
        queryset = queryset.filter(article_id=article_id)
    if status is not None:
        queryset = queryset.filter(status=_validate_status(status))
    return queryset


def article_decisions(*, review, article_id):
    article = get_child(review.article_set, article_id, label="Article")
    return article.decisions.select_related("user", "selection_criteria")


def reviewers(review, *, stage=None):
    """Users who recorded at least one decision (optionally at a stage), ordered by username."""
    queryset = review.decisions.all()
    if stage is not None:
        queryset = queryset.filter(stage=_validate_stage(stage))
    ids = queryset.values_list("user_id", flat=True).distinct()
    return User.objects.filter(pk__in=ids).order_by("username")


def _decision_table(review, stage):
    """{article_id: {user_id: status}} for a stage."""
    table = defaultdict(dict)
    for row in review.decisions.filter(stage=stage).values_list("article_id", "user_id", "status"):
        table[row[0]][row[1]] = row[2]
    return table


def cohens_kappa(pairs):
    """
    Cohen's kappa for a list of (rating_a, rating_b) pairs. Returns None when there are no pairs; 1.0 when both
    raters agree on everything with a single category (pe == 1).
    """
    pairs = list(pairs)
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    counts_a, counts_b = Counter(a for a, _b in pairs), Counter(b for _a, b in pairs)
    expected = sum((counts_a[k] / n) * (counts_b[k] / n) for k in set(counts_a) | set(counts_b))
    if expected >= 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def interpret_kappa(kappa):
    """Landis & Koch (1977) labels, as commonly reported in SLRs."""
    if kappa is None:
        return "no overlap"
    if kappa < 0:
        return "poor"
    if kappa < 0.21:
        return "slight"
    if kappa < 0.41:
        return "fair"
    if kappa < 0.61:
        return "moderate"
    if kappa < 0.81:
        return "substantial"
    return "almost perfect"


def agreement(*, review, stage=StudyDecision.TITLE_ABSTRACT, user_a_id=None, user_b_id=None):
    """
    Agreement between two reviewers at a stage (defaults to the first two reviewers found). Only articles both
    decided are compared.
    """
    stage = _validate_stage(stage)
    people = list(reviewers(review, stage=stage))
    if user_a_id is None or user_b_id is None:
        if len(people) < 2:
            raise ValidationError("At least two reviewers must have recorded decisions at this stage.")
        user_a, user_b = people[0], people[1]
    else:
        by_id = {u.pk: u for u in people}
        try:
            user_a, user_b = by_id[int(user_a_id)], by_id[int(user_b_id)]
        except (KeyError, ValueError, TypeError):
            raise NotFound("Both users must have recorded decisions at this stage.")
    table = _decision_table(review, stage)
    pairs = [
        (statuses[user_a.pk], statuses[user_b.pk])
        for statuses in table.values()
        if user_a.pk in statuses and user_b.pk in statuses
    ]
    kappa = cohens_kappa(pairs)
    agreed = sum(1 for a, b in pairs if a == b)
    return {
        "stage": stage,
        "user_a": user_a.username,
        "user_b": user_b.username,
        "compared": len(pairs),
        "agreed": agreed,
        "percent_agreement": (agreed / len(pairs)) if pairs else None,
        "kappa": kappa,
        "interpretation": interpret_kappa(kappa),
        "reviewers": [u.username for u in people],
    }


def disagreements(*, review, stage=StudyDecision.TITLE_ABSTRACT):
    """Articles with at least two decisions that differ at the stage."""
    stage = _validate_stage(stage)
    table = _decision_table(review, stage)
    conflicting = [article_id for article_id, statuses in table.items() if len(set(statuses.values())) > 1]
    rows = []
    decisions = review.decisions.filter(stage=stage, article_id__in=conflicting).select_related(
        "user", "selection_criteria"
    )
    by_article = defaultdict(list)
    for decision in decisions:
        by_article[decision.article_id].append(decision)
    for article in review.article_set.filter(pk__in=conflicting).order_by("title", "pk"):
        rows.append({"article": article, "decisions": by_article[article.pk]})
    return rows


def _apply_rule(rule, statuses):
    """Consolidated status for one article given {user_id: status}, or None when the rule cannot decide."""
    values = list(statuses.values())
    if not values:
        return None
    if rule == RULE_UNANIMOUS:
        return values[0] if len(set(values)) == 1 else None
    if rule == RULE_ANY_INCLUDE:
        if Article.ACCEPTED in values:
            return Article.ACCEPTED
        return values[0] if len(set(values)) == 1 else None
    if rule == RULE_MAJORITY:
        (top, count), *rest = Counter(values).most_common()
        if rest and rest[0][1] == count:
            return None
        return top
    raise ValidationError(f"rule must be one of {RULES}.", field="rule")


@transaction.atomic
def consolidate(*, review, stage=StudyDecision.TITLE_ABSTRACT, rule=RULE_UNANIMOUS, actor=None, article_ids=None):
    """
    Set ``Article.status`` from the reviewers' decisions using ``rule``. Articles the rule cannot decide are left
    untouched and reported as unresolved. Returns counts and the ids involved.
    """
    stage = _validate_stage(stage)
    if rule not in RULES:
        raise ValidationError(f"rule must be one of {RULES}.", field="rule")
    table = _decision_table(review, stage)
    if article_ids is not None:
        wanted = {a.pk for a in get_children(review.article_set, article_ids, label="Article")}
        table = {k: v for k, v in table.items() if k in wanted}
    resolved, unresolved = {}, []
    for article_id, statuses in table.items():
        status = _apply_rule(rule, statuses)
        if status is None:
            unresolved.append(article_id)
        else:
            resolved[article_id] = status
    for status in set(resolved.values()):
        ids = [a for a, s in resolved.items() if s == status]
        review.article_set.filter(pk__in=ids).update(status=status, updated_by=actor)
    return {
        "stage": stage,
        "rule": rule,
        "resolved": len(resolved),
        "unresolved": len(unresolved),
        "resolved_ids": sorted(resolved),
        "unresolved_ids": sorted(unresolved),
    }


def summary(review):
    """Decision counts per stage and reviewer, for the overview."""
    rows = []
    for stage, _label in StudyDecision.STAGES:
        per_user = Counter(review.decisions.filter(stage=stage).values_list("user__username", flat=True))
        if per_user:
            rows.append({"stage": stage, "reviewers": dict(per_user), "articles": len(_decision_table(review, stage))})
    return rows
