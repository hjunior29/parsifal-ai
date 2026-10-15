from parsifal.apps.core.exceptions import NotFound, ValidationError


def get_child(queryset, pk, *, label):
    """Fetch a child object of a review by primary key, raising NotFound when it is absent or out of scope."""
    try:
        return queryset.get(pk=pk)
    except (queryset.model.DoesNotExist, ValueError, TypeError):
        raise NotFound(f"{label} {pk!r} not found in this review.")


def get_children(queryset, pks, *, label):
    """Fetch several children by primary key; every id must belong to the review."""
    pks = list(dict.fromkeys(pks))
    objects = list(queryset.filter(pk__in=pks))
    if len(objects) != len(pks):
        found = {obj.pk for obj in objects}
        missing = [pk for pk in pks if pk not in found]
        raise NotFound(f"{label} {missing} not found in this review.")
    return objects


def check_length(value, limit, *, field):
    if value is not None and len(value) > limit:
        raise ValidationError(f"{field} must have at most {limit} characters (got {len(value)}).", field=field)
    return value


def require(value, *, field, message=None):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValidationError(message or f"{field} is required.", field=field)
    return value


def reorder(queryset, ordered_ids, *, label):
    """Assign ``order`` = position for the given ids; ids must all belong to the queryset."""
    objects = {obj.pk: obj for obj in get_children(queryset, ordered_ids, label=label)}
    for position, pk in enumerate(ordered_ids):
        obj = objects[pk]
        if obj.order != position:
            obj.order = position
            obj.save(update_fields=["order"])
    return [objects[pk] for pk in ordered_ids]
