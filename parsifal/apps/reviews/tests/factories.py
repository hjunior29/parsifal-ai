import factory
from factory.django import DjangoModelFactory

from parsifal.apps.authentication.tests.factories import UserFactory
from parsifal.apps.reviews.models import (
    Article,
    DataExtractionField,
    DataExtractionLookup,
    Keyword,
    QualityAnswer,
    QualityQuestion,
    Question,
    Review,
    SelectionCriteria,
    Source,
)


class ReviewFactory(DjangoModelFactory):
    name = factory.Sequence(lambda n: f"slr-{n}")
    title = factory.Sequence(lambda n: f"Test SLR #{n}")
    author = factory.SubFactory(UserFactory)

    class Meta:
        model = Review
        django_get_or_create = ("name",)

    @factory.post_generation
    def co_authors(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            self.co_authors.add(*extracted)

    @factory.post_generation
    def sources(self, create, extracted, **kwargs):
        if not create:
            return

        if extracted:
            self.sources.add(*extracted)


class SourceFactory(DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Source #{n}")
    url = factory.Sequence(lambda n: f"https://source-{n}.example.com")
    is_default = False

    class Meta:
        model = Source
        django_get_or_create = ("name",)


class DefaultSourceFactory(SourceFactory):
    is_default = True


class ArticleFactory(DjangoModelFactory):
    review = factory.SubFactory(ReviewFactory)
    source = factory.SubFactory(SourceFactory)
    bibtex_key = factory.Sequence(lambda n: f"key{n}")
    title = factory.Sequence(lambda n: f"Article #{n}")
    author = "Doe, J."
    year = "2020"

    class Meta:
        model = Article


class QuestionFactory(DjangoModelFactory):
    review = factory.SubFactory(ReviewFactory)
    question = factory.Sequence(lambda n: f"Research question #{n}?")
    order = factory.Sequence(lambda n: n)

    class Meta:
        model = Question


class KeywordFactory(DjangoModelFactory):
    review = factory.SubFactory(ReviewFactory)
    description = factory.Sequence(lambda n: f"keyword-{n}")
    related_to = Keyword.POPULATION

    class Meta:
        model = Keyword


class SelectionCriteriaFactory(DjangoModelFactory):
    review = factory.SubFactory(ReviewFactory)
    description = factory.Sequence(lambda n: f"Criteria #{n}")
    criteria_type = SelectionCriteria.INCLUSION

    class Meta:
        model = SelectionCriteria


class QualityQuestionFactory(DjangoModelFactory):
    review = factory.SubFactory(ReviewFactory)
    description = factory.Sequence(lambda n: f"Quality question #{n}?")
    order = factory.Sequence(lambda n: n)

    class Meta:
        model = QualityQuestion


class QualityAnswerFactory(DjangoModelFactory):
    review = factory.SubFactory(ReviewFactory)
    description = factory.Sequence(lambda n: f"Answer #{n}")
    weight = 1.0

    class Meta:
        model = QualityAnswer


class DataExtractionFieldFactory(DjangoModelFactory):
    review = factory.SubFactory(ReviewFactory)
    description = factory.Sequence(lambda n: f"Field #{n}")
    field_type = DataExtractionField.STRING_FIELD
    order = factory.Sequence(lambda n: n)

    class Meta:
        model = DataExtractionField


class DataExtractionLookupFactory(DjangoModelFactory):
    field = factory.SubFactory(DataExtractionFieldFactory, field_type=DataExtractionField.SELECT_MANY_FIELD)
    value = factory.Sequence(lambda n: f"Option {n}")

    class Meta:
        model = DataExtractionLookup
