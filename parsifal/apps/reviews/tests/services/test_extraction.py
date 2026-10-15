import datetime

from django.test import TestCase

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import DataExtraction, DataExtractionField
from parsifal.apps.reviews.services import extraction
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    DataExtractionFieldFactory,
    DataExtractionLookupFactory,
    ReviewFactory,
    SourceFactory,
)


class TestFields(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.review = ReviewFactory()

    def test_add_select_field_with_lookups(self):
        field = extraction.add_field(
            review=self.review,
            description="Method",
            field_type="O",
            lookup_values=["Case study", " Survey ", "", "Survey"],
        )
        self.assertEqual(
            ["Case study", "Survey"], list(field.dataextractionlookup_set.values_list("value", flat=True))
        )

    def test_update_lookups_syncs(self):
        field = extraction.add_field(review=self.review, description="M", field_type="M", lookup_values=["a", "b"])
        keep = field.dataextractionlookup_set.get(value="a")
        extraction.update_field(review=self.review, field_id=field.pk, lookup_values=["a", "c"])
        self.assertEqual(["a", "c"], list(field.dataextractionlookup_set.values_list("value", flat=True)))
        with self.subTest(msg="existing lookup row preserved"):
            self.assertTrue(field.dataextractionlookup_set.filter(pk=keep.pk).exists())

    def test_type_change_clears_values_and_lookups(self):
        source = SourceFactory()
        self.review.sources.add(source)
        article = ArticleFactory(review=self.review, source=source)
        field = extraction.add_field(review=self.review, description="M", field_type="M", lookup_values=["a"])
        lookup = field.dataextractionlookup_set.get()
        extraction.set_value(review=self.review, article_id=article.pk, field_id=field.pk, values=[lookup.pk])
        extraction.update_field(review=self.review, field_id=field.pk, field_type="S")
        row = DataExtraction.objects.get(article=article, field=field)
        self.assertEqual(("", 0, 0), (row.value, row.select_values.count(), field.dataextractionlookup_set.count()))

    def test_invalid_type_reorder_and_scoping(self):
        with self.assertRaises(ValidationError):
            extraction.add_field(review=self.review, description="x", field_type="Z")
        fields = DataExtractionFieldFactory.create_batch(2, review=self.review)
        extraction.reorder_fields(review=self.review, ordered_ids=[fields[1].pk, fields[0].pk])
        self.assertEqual(fields[1].pk, self.review.dataextractionfield_set.order_by("order").first().pk)
        with self.assertRaises(NotFound):
            extraction.remove_field(review=self.review, field_id=DataExtractionFieldFactory().pk)


class TestValues(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.actor = cls.review.author
        cls.article = ArticleFactory(review=cls.review, source=cls.source, status="A")

    def field(self, field_type, lookups=()):
        field = DataExtractionFieldFactory(review=self.review, field_type=field_type)
        for value in lookups:
            DataExtractionLookupFactory(field=field, value=value)
        return field

    def set(self, field, **kwargs):
        return extraction.set_value(
            review=self.review, article_id=self.article.pk, field_id=field.pk, actor=self.actor, **kwargs
        )

    def test_coercions(self):
        cases = (
            (DataExtractionField.BOOLEAN_FIELD, "True", True),
            (DataExtractionField.STRING_FIELD, "  text  ", "text"),
            (DataExtractionField.FLOAT_FIELD, "3,5", 3.5),
            (DataExtractionField.INTEGER_FIELD, "42.0", 42),
            (DataExtractionField.DATE_FIELD, "12/31/2020", "2020-12-31"),
        )
        for field_type, raw, expected in cases:
            with self.subTest(field_type=field_type):
                field = self.field(field_type)
                row = self.set(field, value=raw)
                self.assertEqual(expected, extraction.serialize_value(field, row))
                self.assertEqual(self.actor, row.user)

    def test_invalid_coercion_raises_validation_error(self):
        for field_type, raw in (
            (DataExtractionField.BOOLEAN_FIELD, "maybe"),
            (DataExtractionField.FLOAT_FIELD, "abc"),
            (DataExtractionField.INTEGER_FIELD, "1.5x"),
            (DataExtractionField.DATE_FIELD, "2020-12-31"),
        ):
            with self.subTest(field_type=field_type):
                with self.assertRaises(ValidationError):
                    self.set(self.field(field_type), value=raw)

    def test_select_one_and_many_have_set_semantics(self):
        one = self.field(DataExtractionField.SELECT_ONE_FIELD, ["x", "y"])
        x, y = one.dataextractionlookup_set.order_by("value")
        self.set(one, value=x.pk)
        self.set(one, value=y.pk)
        self.assertEqual(
            "y", extraction.serialize_value(one, DataExtraction.objects.get(article=self.article, field=one))
        )
        self.set(one, value=None)
        self.assertIsNone(extraction.serialize_value(one, DataExtraction.objects.get(article=self.article, field=one)))

        many = self.field(DataExtractionField.SELECT_MANY_FIELD, ["a", "b", "c"])
        a, b, c = many.dataextractionlookup_set.order_by("value")
        self.set(many, values=[a.pk, b.pk])
        self.set(many, values=[b.pk, c.pk])
        row = DataExtraction.objects.get(article=self.article, field=many)
        self.assertEqual(["b", "c"], sorted(extraction.serialize_value(many, row)))

    def test_toggle_legacy_semantics(self):
        many = self.field(DataExtractionField.SELECT_MANY_FIELD, ["a"])
        lookup = many.dataextractionlookup_set.get()
        extraction.toggle_select_value(
            review=self.review, article_id=self.article.pk, field_id=many.pk, lookup_id=lookup.pk
        )
        self.assertEqual(1, DataExtraction.objects.get(article=self.article, field=many).select_values.count())
        extraction.toggle_select_value(
            review=self.review, article_id=self.article.pk, field_id=many.pk, lookup_id=lookup.pk
        )
        self.assertEqual(0, DataExtraction.objects.get(article=self.article, field=many).select_values.count())
        with self.assertRaises(ValidationError):
            extraction.toggle_select_value(
                review=self.review, article_id=self.article.pk, field_id=self.field("S").pk, lookup_id=lookup.pk
            )

    def test_lookup_scoping(self):
        many = self.field(DataExtractionField.SELECT_MANY_FIELD, ["a"])
        foreign_lookup = DataExtractionLookupFactory()
        with self.assertRaises(NotFound):
            self.set(many, values=[foreign_lookup.pk])

    def test_mark_done_and_article_values(self):
        extraction.mark_done(review=self.review, article_id=self.article.pk, done=True)
        self.article.refresh_from_db()
        self.assertTrue(self.article.finished_data_extraction)
        field = self.field(DataExtractionField.DATE_FIELD)
        self.set(field, value="01/02/2021")
        rows = extraction.article_values(review=self.review, article_id=self.article.pk)
        self.assertEqual([(field.pk, "2021-01-02")], [(r["field"].pk, r["value"]) for r in rows])
        self.assertEqual(datetime.date(2021, 1, 2), rows[0]["extraction"].get_value())
