import datetime
import re

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse
from django.utils.html import escape
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class Source(models.Model):
    name = models.CharField(max_length=100)
    url = models.CharField(max_length=200)
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("Source")
        verbose_name_plural = _("Sources")
        ordering = ("name",)

    def __str__(self):
        return self.name

    def set_url(self, value):
        if "http://" not in value and "https://" not in value and len(value) > 0:
            self.url = "http://{0}".format(value)
        else:
            self.url = value


class Review(models.Model):
    UNPUBLISHED = "U"
    PUBLISHED = "P"
    REVIEW_STATUS = (
        (UNPUBLISHED, "Unpublished"),
        (PUBLISHED, "Published"),
    )

    # Kitchenham & Charters (2007) systematic literature review, or Petersen et al. (2015) systematic mapping
    # study. The type drives which steps are expected (quality assessment is optional for maps) and the report.
    SLR = "slr"
    MAPPING = "mapping"
    REVIEW_TYPES = (
        (SLR, _("Systematic literature review")),
        (MAPPING, _("Systematic mapping study")),
    )

    name = models.SlugField(_("name"), max_length=255)
    title = models.CharField(_("title"), max_length=255)
    description = models.CharField(_("description"), max_length=500, blank=True)
    author = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name=_("author"))
    create_date = models.DateTimeField(_("date created"), auto_now_add=True)
    last_update = models.DateTimeField(_("last update"), auto_now=True)
    objective = models.TextField(_("objective"), max_length=1000, blank=True)
    sources = models.ManyToManyField(Source, verbose_name=_("sources"))
    status = models.CharField(_("status"), max_length=1, choices=REVIEW_STATUS, default=UNPUBLISHED)
    co_authors = models.ManyToManyField(User, related_name="co_authors", verbose_name=_("co-authors"))
    quality_assessment_cutoff_score = models.FloatField(_("quality assessment cutoff score"), default=0.0)
    population = models.CharField(_("population"), max_length=200, blank=True)
    intervention = models.CharField(_("intervention"), max_length=200, blank=True)
    comparison = models.CharField(_("comparison"), max_length=200, blank=True)
    outcome = models.CharField(_("outcome"), max_length=200, blank=True)
    context = models.CharField(_("context"), max_length=200, blank=True)
    review_type = models.CharField(_("review type"), max_length=10, choices=REVIEW_TYPES, default=SLR)
    # Protocol sections recommended by the guidelines but not modelled upstream (K 5.4, P 5.1.5)
    selection_procedure = models.TextField(_("study selection procedure"), blank=True)
    synthesis_strategy = models.TextField(_("synthesis strategy"), blank=True)
    validity_threats = models.TextField(_("validity threats"), blank=True)

    class Meta:
        verbose_name = _("review")
        verbose_name_plural = _("reviews")
        unique_together = (("name", "author"),)

    def __str__(self):
        return self.name

    @property
    def is_mapping_study(self):
        return self.review_type == self.MAPPING

    def get_absolute_url(self):
        return reverse("review", args=(self.author.username, self.name))

    def get_questions(self):
        questions = Question.objects.filter(review__id=self.id)
        return questions

    def get_inclusion_criterias(self):
        return SelectionCriteria.objects.filter(review__id=self.id, criteria_type="I")

    def get_exclusion_criterias(self):
        return SelectionCriteria.objects.filter(review__id=self.id, criteria_type="E")

    def get_keywords(self):
        return Keyword.objects.filter(review__id=self.id, synonym_of=None)

    def is_author_or_coauthor(self, user):
        if user.id == self.author.id:
            return True
        for co_author in self.co_authors.all():
            if user.id == co_author.id:
                return True
        return False

    def get_generic_search_string(self):
        try:
            search_string = SearchSession.objects.filter(review__id=self.id, source=None)[:1].get()
        except SearchSession.DoesNotExist:
            search_string = SearchSession(review=self)
        return search_string

    def get_latest_source_search_strings(self):
        return self.searchsession_set.exclude(source=None).order_by("source__name")

    def get_source_articles(self, source_id=None):
        queryset = Article.objects.filter(review__id=self.id).select_related("created_by__profile")

        if source_id is not None:
            queryset = queryset.filter(source__id=source_id)
        return queryset

    def get_duplicate_articles(self):
        articles = Article.objects.filter(review__id=self.id).exclude(status=Article.DUPLICATED).order_by("title")
        grouped_articles = dict()

        for article in articles:
            slug = slugify(article.title)
            if slug not in grouped_articles.keys():
                grouped_articles[slug] = {"size": 0, "articles": list()}
            grouped_articles[slug]["size"] += 1
            grouped_articles[slug]["articles"].append(article)

        duplicates = list()
        for slug, data in grouped_articles.items():
            if data["size"] > 1:
                duplicates.append(data["articles"])

        return duplicates

    def get_accepted_articles(self):
        return Article.objects.filter(review__id=self.id, status=Article.ACCEPTED)

    def get_final_selection_articles(self):
        accepted_articles = Article.objects.filter(review__id=self.id, status=Article.ACCEPTED).annotate(
            score=Coalesce(Sum("qualityassessment__answer__weight"), Value(0.0))
        )
        if self.has_quality_assessment_checklist() and self.quality_assessment_cutoff_score > 0.0:
            accepted_articles = accepted_articles.filter(score__gt=self.quality_assessment_cutoff_score)
        return accepted_articles

    def has_quality_assessment_checklist(self):
        has_questions = self.qualityquestion_set.exists()
        has_answers = self.qualityanswer_set.exists()
        return has_questions and has_answers

    def get_data_extraction_fields(self):
        return DataExtractionField.objects.filter(review__id=self.id)

    def get_quality_assessment_questions(self):
        return QualityQuestion.objects.filter(review__id=self.id)

    def get_quality_assessment_answers(self):
        return QualityAnswer.objects.filter(review__id=self.id)

    def calculate_quality_assessment_max_score(self):
        try:
            questions_count = QualityQuestion.objects.filter(review__id=self.id).count()
            higher_weight_answer = QualityAnswer.objects.filter(review__id=self.id).order_by("-weight")[:1].get()
            if questions_count and higher_weight_answer:
                return questions_count * higher_weight_answer.weight
            else:
                return 0.0
        except Exception:
            return 0.0


class Question(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="research_questions")
    question = models.CharField(max_length=500)
    parent_question = models.ForeignKey("self", on_delete=models.CASCADE, null=True, related_name="+")
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Question"
        verbose_name_plural = "Questions"
        ordering = ("order",)

    def __str__(self):
        return self.question

    def get_child_questions(self):
        return Question.objects.filter(parent_question=self)


class SelectionCriteria(models.Model):
    INCLUSION = "I"
    EXCLUSION = "E"
    SELECTION_TYPES = (
        (INCLUSION, "Inclusion"),
        (EXCLUSION, "Exclusion"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    criteria_type = models.CharField(max_length=1, choices=SELECTION_TYPES)
    description = models.CharField(max_length=200)

    class Meta:
        verbose_name = "Selection Criteria"
        verbose_name_plural = "Selection Criterias"
        ordering = ("description",)

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        self.description = self.description[:200]
        super().save(*args, **kwargs)


class SearchSession(models.Model):
    DATABASE = "database"
    SNOWBALLING = "snowballing"
    MANUAL = "manual"
    OTHER = "other"
    SEARCH_TYPES = (
        (DATABASE, _("Database search")),
        (SNOWBALLING, _("Snowballing")),
        (MANUAL, _("Manual search")),
        (OTHER, _("Other")),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, null=True)
    search_string = models.TextField(max_length=10000)
    version = models.IntegerField(default=1)
    # Search documentation (Kitchenham 6.1.4 Table 2; Petersen 5.1.2)
    search_type = models.CharField(_("search type"), max_length=12, choices=SEARCH_TYPES, default=DATABASE)
    searched_at = models.DateField(_("date of search"), null=True, blank=True)
    years_from = models.IntegerField(_("years covered (from)"), null=True, blank=True)
    years_to = models.IntegerField(_("years covered (to)"), null=True, blank=True)
    result_count = models.IntegerField(_("number of results"), null=True, blank=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("review", "source"), name="unique_search_session_per_source"),
            models.UniqueConstraint(
                fields=("review",), condition=Q(source__isnull=True), name="unique_generic_search_session"
            ),
        )

    def __str__(self):
        return self.search_string

    def search_string_as_html(self):
        escaped_string = escape(self.search_string)
        html = escaped_string.replace(" OR ", " <strong>OR</strong> ").replace(" AND ", " <strong>AND</strong> ")
        return html


def search_result_file_upload_to(instance, filename):
    """Kept only because historical migration 0020 references it; the SearchResult model was removed."""
    return "reviews/{0}/search_result/".format(instance.review.pk)


class Article(models.Model):
    UNCLASSIFIED = "U"
    REJECTED = "R"
    ACCEPTED = "A"
    DUPLICATED = "D"
    ARTICLE_STATUS = (
        (UNCLASSIFIED, "Unclassified"),
        (REJECTED, "Rejected"),
        (ACCEPTED, "Accepted"),
        (DUPLICATED, "Duplicated"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    bibtex_key = models.CharField(max_length=100)
    title = models.CharField(max_length=1000, null=True, blank=True, db_index=True)
    author = models.CharField(max_length=1000, null=True, blank=True)
    journal = models.CharField(max_length=1000, null=True, blank=True)
    year = models.CharField(max_length=10, null=True, blank=True, db_index=True)
    year_int = models.IntegerField(_("year (numeric)"), null=True, blank=True, db_index=True, editable=False)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, null=True)
    pages = models.CharField(max_length=20, null=True, blank=True)
    volume = models.CharField(max_length=100, null=True, blank=True)
    abstract = models.TextField(max_length=4000, null=True, blank=True)
    document_type = models.CharField(max_length=100, null=True, blank=True)
    status = models.CharField(max_length=1, choices=ARTICLE_STATUS, default=UNCLASSIFIED)
    comments = models.TextField(max_length=2000, null=True, blank=True)
    doi = models.CharField(max_length=50, null=True, blank=True)
    url = models.CharField(max_length=500, null=True, blank=True)
    affiliation = models.CharField(max_length=500, null=True, blank=True)
    author_keywords = models.CharField(max_length=500, null=True, blank=True)
    keywords = models.CharField(max_length=500, null=True, blank=True)
    publisher = models.CharField(max_length=100, null=True, blank=True)
    issn = models.CharField(max_length=50, null=True, blank=True)
    language = models.CharField(max_length=50, null=True, blank=True)
    note = models.CharField(max_length=500, null=True, blank=True)
    finished_data_extraction = models.BooleanField(default=False)
    selection_criteria = models.ForeignKey(SelectionCriteria, null=True, blank=True, on_delete=models.SET_NULL)
    found_via = models.ForeignKey(
        SearchSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="found_articles",
        verbose_name=_("found via search"),
    )
    created_at = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, blank=True, null=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, related_name="articles_created", on_delete=models.SET_NULL
    )
    updated_by = models.ForeignKey(
        User, null=True, blank=True, related_name="articles_updated", on_delete=models.SET_NULL
    )

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"

    def __str__(self):
        return self.title

    @staticmethod
    def parse_year(value):
        """Extract a four-digit year from the free-text BibTeX year field, or None."""
        match = re.search(r"\d{4}", value or "")
        return int(match.group()) if match else None

    def save(self, *args, **kwargs):
        self.year_int = self.parse_year(self.year)
        super().save(*args, **kwargs)

    def get_score(self):
        score = QualityAssessment.objects.filter(article__id=self.id).aggregate(Sum("answer__weight"))
        if score["answer__weight__sum"] is None:
            return 0.0
        return score["answer__weight__sum"]

    def get_quality_assesment(self):
        quality_assessments = QualityAssessment.objects.filter(article__id=self.id)
        return quality_assessments

    def get_status_html(self):
        label = {
            Article.UNCLASSIFIED: "default",
            Article.REJECTED: "danger",
            Article.ACCEPTED: "success",
            Article.DUPLICATED: "warning",
        }
        return '<span class="label label-{0}">{1}</span>'.format(label[self.status], self.get_status_display())


class Keyword(models.Model):
    POPULATION = "P"
    INTERVENTION = "I"
    COMPARISON = "C"
    OUTCOME = "O"
    RELATED_TO = (
        (POPULATION, "Population"),
        (INTERVENTION, "Intervention"),
        (COMPARISON, "Comparison"),
        (OUTCOME, "Outcome"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="keywords")
    description = models.CharField(max_length=200)
    synonym_of = models.ForeignKey("self", on_delete=models.CASCADE, null=True, related_name="synonyms")
    related_to = models.CharField(max_length=1, choices=RELATED_TO, blank=True)

    class Meta:
        verbose_name = "Keyword"
        verbose_name_plural = "Keywords"
        ordering = ("description",)

    def __str__(self):
        return self.description

    def save(self, *args, **kwargs):
        self.description = self.description[:200]
        super().save(*args, **kwargs)

    def get_synonyms(self):
        return Keyword.objects.filter(review__id=self.review.id, synonym_of__id=self.id)


class QualityAnswer(models.Model):
    SUGGESTED_ANSWERS = (("Yes", 1.0), ("Partially", 0.5), ("No", 0.0))

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    weight = models.FloatField()

    class Meta:
        verbose_name = "Quality Assessment Answer"
        verbose_name_plural = "Quality Assessment Answers"
        ordering = ("-weight",)

    def __str__(self):
        return self.description


class QualityQuestion(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Quality Assessment Question"
        verbose_name_plural = "Quality Assessment Questions"
        ordering = ("order",)

    def __str__(self):
        return self.description


class QualityAssessment(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    question = models.ForeignKey(QualityQuestion, on_delete=models.CASCADE)
    answer = models.ForeignKey(QualityAnswer, on_delete=models.CASCADE, null=True)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("article", "question"), name="unique_quality_assessment_per_question"),
        )

    def __str__(self):
        return str(self.article.id) + " " + str(self.question.id)


class DataExtractionField(models.Model):
    BOOLEAN_FIELD = "B"
    STRING_FIELD = "S"
    FLOAT_FIELD = "F"
    INTEGER_FIELD = "I"
    DATE_FIELD = "D"
    SELECT_ONE_FIELD = "O"
    SELECT_MANY_FIELD = "M"
    FIELD_TYPES = (
        (BOOLEAN_FIELD, "Boolean Field"),
        (STRING_FIELD, "String Field"),
        (FLOAT_FIELD, "Float Field"),
        (INTEGER_FIELD, "Integer Field"),
        (DATE_FIELD, "Date Field"),
        (SELECT_ONE_FIELD, "Select One Field"),
        (SELECT_MANY_FIELD, "Select Many Field"),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    field_type = models.CharField(max_length=1, choices=FIELD_TYPES)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Data Extraction Field"
        verbose_name_plural = "Data Extraction Fields"
        ordering = ("order",)

    def get_select_values(self):
        return DataExtractionLookup.objects.filter(field__id=self.id)

    def is_select_field(self):
        return self.field_type in (self.SELECT_ONE_FIELD, self.SELECT_MANY_FIELD)


class DataExtractionLookup(models.Model):
    field = models.ForeignKey(DataExtractionField, on_delete=models.CASCADE)
    value = models.CharField(max_length=1000)

    class Meta:
        verbose_name = "Lookup Value"
        verbose_name_plural = "Lookup Values"
        ordering = ("value",)

    def __str__(self):
        return self.value


class DataExtraction(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    article = models.ForeignKey(Article, on_delete=models.CASCADE)
    field = models.ForeignKey(DataExtractionField, on_delete=models.CASCADE)
    value = models.TextField(blank=True, null=True)
    select_values = models.ManyToManyField(DataExtractionLookup)

    class Meta:
        constraints = (models.UniqueConstraint(fields=("article", "field"), name="unique_data_extraction_per_field"),)

    def _set_boolean_value(self, value):
        if value:
            if value in ["True", "False"]:
                self.value = value
            else:
                raise ValueError('Expected values: "True" or "False"')
        else:
            self.value = ""

    def _set_string_value(self, value):
        self.value = value.strip()

    def _set_float_value(self, value):
        try:
            if value:
                _value = value.replace(",", ".")
                self.value = float(_value)
            else:
                self.value = ""
        except Exception:
            raise Exception(
                "Invalid input for "
                + self.field.description
                + " field. Expected value: floating point number. Please use dot instead of comma."
            )

    def _set_integer_value(self, value):
        try:
            if value:
                _value = value.replace(",", ".")
                self.value = int(float(_value))
            else:
                self.value = ""
        except Exception:
            raise Exception("Invalid input for " + self.field.description + " field. Expected value: integer number.")

    def _set_date_value(self, value):
        try:
            if value:
                _value = datetime.datetime.strptime(value, "%m/%d/%Y").date()
                self.value = str(_value)
            else:
                self.value = ""
        except Exception:
            raise Exception(
                "Invalid input for "
                + self.field.description
                + " field. Expected value: date. Please use the format MM/DD/YYYY."
            )

    def _set_select_one_value(self, value):
        self.value = ""
        self.select_values.clear()
        if value:
            _value = DataExtractionLookup.objects.get(pk=value)
            self.select_values.add(_value)

    def _set_select_many_value(self, value):
        self.value = ""
        _value = DataExtractionLookup.objects.get(pk=value)
        if _value in self.select_values.all():
            self.select_values.remove(_value)
        else:
            self.select_values.add(_value)

    def set_value(self, value):
        set_value_functions = {
            DataExtractionField.BOOLEAN_FIELD: self._set_boolean_value,
            DataExtractionField.STRING_FIELD: self._set_string_value,
            DataExtractionField.FLOAT_FIELD: self._set_float_value,
            DataExtractionField.INTEGER_FIELD: self._set_integer_value,
            DataExtractionField.DATE_FIELD: self._set_date_value,
            DataExtractionField.SELECT_ONE_FIELD: self._set_select_one_value,
            DataExtractionField.SELECT_MANY_FIELD: self._set_select_many_value,
        }
        set_value_functions[self.field.field_type](value[:1000])

    def _get_boolean_value(self):
        try:
            if self.value == "True":
                return True
            elif self.value == "False":
                return False
            else:
                return ""
        except Exception:
            return ""

    def _get_string_value(self):
        return self.value

    def _get_float_value(self):
        try:
            return float(self.value)
        except Exception:
            return ""

    def _get_integer_value(self):
        try:
            return int(self.value)
        except Exception:
            return ""

    def _get_date_value(self):
        try:
            if self.value != "":
                return datetime.datetime.strptime(self.value, "%Y-%m-%d").date()
            else:
                return ""
        except Exception:
            return ""

    def _get_select_one_value(self):
        try:
            return self.select_values.all()[0]
        except Exception:
            return None

    def _get_select_many_value(self):
        try:
            return self.select_values.all()
        except Exception:
            return []

    def get_value(self):
        if self.field.field_type:
            get_value_functions = {
                DataExtractionField.BOOLEAN_FIELD: self._get_boolean_value,
                DataExtractionField.STRING_FIELD: self._get_string_value,
                DataExtractionField.FLOAT_FIELD: self._get_float_value,
                DataExtractionField.INTEGER_FIELD: self._get_integer_value,
                DataExtractionField.DATE_FIELD: self._get_date_value,
                DataExtractionField.SELECT_ONE_FIELD: self._get_select_one_value,
                DataExtractionField.SELECT_MANY_FIELD: self._get_select_many_value,
            }
            return get_value_functions[self.field.field_type]()
        return self._get_string_value()

    def get_date_value_as_string(self):
        try:
            value = self.get_value()
            return value.strftime("%m/%d/%Y")
        except Exception:
            return ""


# ---------------------------------------------------------------------------------------------------------------------
# Systematic mapping studies (Petersen et al. 2015)
# ---------------------------------------------------------------------------------------------------------------------


class ClassificationFacet(models.Model):
    """A dimension used to classify studies (research type, research method, venue, topic-specific scheme...)."""

    FIXED = "fixed"
    EMERGING = "emerging"
    KINDS = (
        (FIXED, _("Fixed (topic-independent)")),
        (EMERGING, _("Emerging (topic-specific, built during keywording)")),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="facets")
    name = models.CharField(_("name"), max_length=100)
    description = models.CharField(_("description"), max_length=500, blank=True)
    kind = models.CharField(_("kind"), max_length=10, choices=KINDS, default=EMERGING)
    template = models.CharField(_("template"), max_length=30, blank=True)
    multiple = models.BooleanField(_("allow several categories per study"), default=False)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = _("classification facet")
        verbose_name_plural = _("classification facets")
        ordering = ("order", "pk")
        constraints = (models.UniqueConstraint(fields=("review", "name"), name="unique_facet_name_per_review"),)

    def __str__(self):
        return self.name


class ClassificationCategory(models.Model):
    facet = models.ForeignKey(ClassificationFacet, on_delete=models.CASCADE, related_name="categories")
    name = models.CharField(_("name"), max_length=200)
    description = models.CharField(_("description"), max_length=500, blank=True)
    order = models.IntegerField(default=0)

    class Meta:
        verbose_name = _("classification category")
        verbose_name_plural = _("classification categories")
        ordering = ("order", "pk")
        constraints = (models.UniqueConstraint(fields=("facet", "name"), name="unique_category_name_per_facet"),)

    def __str__(self):
        return self.name


class ArticleClassification(models.Model):
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="classifications")
    facet = models.ForeignKey(ClassificationFacet, on_delete=models.CASCADE, related_name="classifications")
    category = models.ForeignKey(ClassificationCategory, on_delete=models.CASCADE, related_name="classifications")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(_("notes"), blank=True)
    classified_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("article classification")
        verbose_name_plural = _("article classifications")
        constraints = (
            models.UniqueConstraint(fields=("article", "facet", "category"), name="unique_article_facet_category"),
        )


class ReviewTestSetArticle(models.Model):
    """A known relevant paper used to evaluate the search (Petersen 5.1.2 'paper test-set')."""

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="test_set")
    title = models.CharField(_("title"), max_length=1000)
    doi = models.CharField(_("DOI"), max_length=100, blank=True)
    notes = models.CharField(_("notes"), max_length=500, blank=True)
    matched_article = models.ForeignKey(
        Article, null=True, blank=True, on_delete=models.SET_NULL, related_name="test_set_matches"
    )

    class Meta:
        verbose_name = _("test-set article")
        verbose_name_plural = _("test-set articles")
        ordering = ("pk",)

    def __str__(self):
        return self.title


class ProcessChecklistItem(models.Model):
    """One of the actions of Petersen et al. (2015) Table 8, used to self-assess the mapping process."""

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="checklist_items")
    key = models.CharField(_("action"), max_length=50)
    applied = models.BooleanField(default=False)
    notes = models.CharField(_("notes"), max_length=500, blank=True)

    class Meta:
        verbose_name = _("process checklist item")
        verbose_name_plural = _("process checklist items")
        constraints = (models.UniqueConstraint(fields=("review", "key"), name="unique_checklist_item_per_review"),)

    def __str__(self):
        return self.key


# ---------------------------------------------------------------------------------------------------------------------
# Multi-reviewer study selection (Kitchenham 6.2.3, Petersen 5.1.2)
# ---------------------------------------------------------------------------------------------------------------------


class StudyDecision(models.Model):
    """
    One reviewer's (human or agent) decision about one article at one screening stage. ``Article.status``
    remains the consolidated decision; these rows make independent screening and agreement measures possible.
    """

    TITLE_ABSTRACT = "title_abstract"
    FULL_TEXT = "full_text"
    STAGES = (
        (TITLE_ABSTRACT, _("Title and abstract screening")),
        (FULL_TEXT, _("Full-text screening")),
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="decisions")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="decisions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="study_decisions")
    stage = models.CharField(_("stage"), max_length=20, choices=STAGES, default=TITLE_ABSTRACT)
    status = models.CharField(_("decision"), max_length=1, choices=Article.ARTICLE_STATUS)
    selection_criteria = models.ForeignKey(SelectionCriteria, null=True, blank=True, on_delete=models.SET_NULL)
    comments = models.TextField(_("comments"), max_length=2000, blank=True)
    decided_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("study decision")
        verbose_name_plural = _("study decisions")
        ordering = ("article_id", "stage", "user_id")
        constraints = (
            models.UniqueConstraint(fields=("article", "user", "stage"), name="unique_decision_per_reviewer_stage"),
        )

    def __str__(self):
        return f"{self.user.username}: {self.get_status_display()} ({self.get_stage_display()})"


class ReviewAgent(models.Model):
    """
    An AI agent that works on one review as a co-author, with an account of its own so that everything it does is
    attributed to it. The account belongs to the review: deleting the agent (or the review) deletes the account,
    its tokens and everything stored under it.
    """

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="agents")
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="agent_of")
    name = models.CharField(_("name"), max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("review agent")
        verbose_name_plural = _("review agents")
        ordering = ("created_at", "pk")

    def __str__(self):
        return f"{self.name} ({self.user.username})"


@receiver(post_delete, sender=ReviewAgent)
def delete_agent_account(sender, instance, **kwargs):
    """The agent's account never outlives its place in the review (also when the whole review is deleted)."""
    User.objects.filter(pk=instance.user_id).delete()


class ScreeningRun(models.Model):
    """
    One AI exclusion screening (phase 1 of study selection): what was sent to the model, its progress and how it
    ended. The decisions are recorded as ``reviewer``, chosen when the run starts; deleting that account deletes its
    runs with its decisions.
    """

    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"
    FAILED = "failed"
    STATUSES = (
        (RUNNING, _("Running")),  # also while interrupted: it can be continued
        (FINISHED, _("Finished")),
        (CANCELLED, _("Discarded")),  # a new run was started before this one finished
        (FAILED, _("Failed")),  # runs from before runs could be continued
    )

    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="screening_runs")
    reviewer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="screening_runs")
    started_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    model = models.CharField(_("model"), max_length=100)
    # Snapshot of what was sent: review context, extra guidance, exclusion criteria (key, id, description),
    # threshold and scope. The criteria may change later; the snapshot says what Jev saw.
    parameters = models.JSONField(_("parameters"), default=dict)
    status = models.CharField(_("status"), max_length=10, choices=STATUSES, default=RUNNING)
    total = models.PositiveIntegerField(_("studies to screen"), default=0)
    # Why the run is waiting (Jev refused the key or was unavailable); cleared by the next step that works.
    error = models.CharField(_("error"), max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # When a step last ran: a running run without steps for a while was interrupted and can be continued.
    last_step_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("screening run")
        verbose_name_plural = _("screening runs")
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"Screening run {self.pk} ({self.get_status_display()})"


class ScreeningResult(models.Model):
    """What the model answered for one study in a run, kept for audit whether or not the study was rejected."""

    PENDING = "pending"
    EXCLUDED = "excluded"
    PASSED = "passed"
    ERROR = "error"
    OUTCOMES = (
        (PENDING, _("Pending")),
        (EXCLUDED, _("Excluded")),
        (PASSED, _("Passed to the next phase")),
        (ERROR, _("Error")),
    )

    run = models.ForeignKey(ScreeningRun, on_delete=models.CASCADE, related_name="results")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="screening_results")
    # Status of the study when the run took it: unclassified, or rejected by the same reviewer in an earlier run.
    # The run only changes the study if it still has this status.
    previous_status = models.CharField(_("status before the run"), max_length=1, blank=True)
    outcome = models.CharField(_("outcome"), max_length=10, choices=OUTCOMES, default=PENDING)
    p_exclude = models.FloatField(_("probability that an exclusion criterion applies"), null=True, blank=True)
    probabilities = models.JSONField(_("probability of each option"), null=True, blank=True)
    selection_criteria = models.ForeignKey(SelectionCriteria, null=True, blank=True, on_delete=models.SET_NULL)
    model = models.CharField(_("model version that answered"), max_length=100, blank=True)
    error = models.CharField(_("error"), max_length=500, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("screening result")
        verbose_name_plural = _("screening results")
        ordering = ("run_id", "pk")
        constraints = (models.UniqueConstraint(fields=("run", "article"), name="unique_screening_result_per_run"),)

    def __str__(self):
        return f"{self.article_id}: {self.get_outcome_display()}"
