from parsifal_cli.operations import BODY, BY_ID, FILE, FORM, OPERATIONS, PATH, QUERY


def test_operation_ids_and_commands_are_unique():
    ids = [op.id for op in OPERATIONS]
    assert len(ids) == len(set(ids))
    commands = [op.cli_name for op in OPERATIONS]
    assert len(commands) == len(set(commands)), [c for c in commands if commands.count(c) > 1]


def test_path_params_are_declared():
    for op in OPERATIONS:
        placeholders = {segment[1:-1] for segment in op.path.split("/") if segment.startswith("{")}
        placeholders |= {part.split("}")[0] for part in op.path.split("{")[1:]}
        declared = {p.name for p in op.params if p.kind == PATH}
        assert placeholders == declared, (op.id, placeholders, declared)


def test_body_params_only_on_write_operations():
    for op in OPERATIONS:
        kinds = {p.kind for p in op.params}
        if op.method == "GET":
            assert not kinds & {BODY, FORM, FILE}, op.id
        if op.method == "DELETE":
            assert kinds <= {PATH, QUERY}, op.id


# DELETEs that only remove a mark that can be set again: not destructive (no confirmation, no destructiveHint).
REVERSIBLE_DELETES = {"articles_unstar"}


def test_destructive_flags_cover_deletes():
    for op in OPERATIONS:
        if op.method == "DELETE":
            assert op.destructive != (op.id in REVERSIBLE_DELETES), op.id


def test_downloads_are_gets():
    for op in OPERATIONS:
        if op.download:
            assert op.method == "GET"


def test_checks_are_operations_that_take_the_same_values():
    for op in OPERATIONS:
        if op.check:
            check = BY_ID[op.check]
            assert check.method in ("GET", "POST") and check.id != op.id, op.id
            # The check gets the values it shares with the operation, by name: the review at least.
            assert {"review_id"} <= {p.name for p in check.params} & {p.name for p in op.params}, op.id
