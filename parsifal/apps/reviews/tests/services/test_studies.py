from pathlib import Path

from django.test import TestCase

from parsifal.apps.core.exceptions import NotFound, ValidationError
from parsifal.apps.reviews.models import Article
from parsifal.apps.reviews.services import studies, study_columns
from parsifal.apps.reviews.tests.factories import (
    ArticleFactory,
    ReviewFactory,
    SelectionCriteriaFactory,
    SourceFactory,
)

DATA = Path(__file__).resolve().parent.parent / "data"


class TestImportBibtex(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.actor = cls.review.author

    def test_scopus_export_mapping(self):
        result = studies.import_bibtex(
            review=self.review,
            source_id=self.source.pk,
            content=(DATA / "scopus_sample.bib").read_text(),
            actor=self.actor,
        )
        with self.subTest(msg="Test counts"):
            self.assertEqual((2, 0), (result.imported, result.failed))
            self.assertEqual([], result.warnings)

        article = Article.objects.get(review=self.review, bibtex_key="Smith2020")
        expected = {
            "title": "Large language models for systematic literature reviews: a mapping study",
            "author": "Smith, J. and Doe, A.",
            "journal": "Information and Software Technology",
            "year": "2020",
            "year_int": 2020,
            "volume": "128",
            "pages": "106-118",
            "doi": "10.1016/j.infsof.2020.106118",
            "document_type": "Article",
            "url": "https://www.scopus.com/inward/record.uri?eid=2-s2.0-0000000000",
            "author_keywords": "Systematic literature review; Large language models; Mapping study",
            "keywords": "Software engineering; Reviews",
            "publisher": "Elsevier B.V.",
            "issn": "09505849",
            "language": "English",
            "note": "cited By 12",
            "status": Article.UNCLASSIFIED,
        }
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertEqual(value, getattr(article, field))

        with self.subTest(msg="Test provenance"):
            self.assertEqual(self.source, article.source)
            self.assertEqual(self.actor, article.created_by)

    def test_ieee_export_bytes_and_url_alias(self):
        result = studies.import_bibtex(
            review=self.review, source_id=self.source.pk, content=(DATA / "ieee_sample.bib").read_bytes()
        )
        self.assertEqual(2, result.imported)
        article = Article.objects.get(review=self.review, bibtex_key="8812345")
        with self.subTest(msg="Test keywords alias"):
            self.assertEqual("Systematic mapping;Tools;Software engineering", article.keywords)
        with self.subTest(msg="Test url alias"):
            self.assertEqual(
                "https://ieeexplore.ieee.org/document/0000002",
                Article.objects.get(review=self.review, bibtex_key="Duplicate2018").url,
            )

    def test_truncation_is_reported(self):
        content = "@article{long,\n title={%s},\n year={2021}\n}" % ("x" * 1200)
        result = studies.import_bibtex(review=self.review, source_id=self.source.pk, content=content)
        article = Article.objects.get(review=self.review, bibtex_key="long")
        self.assertEqual(1000, len(article.title))
        self.assertEqual(["long: title truncated to 1000 characters."], result.warnings)

    def test_keys_with_spaces_are_recovered_with_their_original_key(self):
        content = (
            "@article{De Pascale2023,\n title={Internet-of-things},\n year={2023},\n doi={10.1002/smr.2511}\n}\n"
            "@article{De_Pascale2023,\n title={Another one},\n year={2022}\n}\n"
            "@article{Plain,\n title={Plain},\n year={2021}\n}\n"
            "@comment{some note, with a comma}\n"
        )
        result = studies.import_bibtex(review=self.review, source_id=self.source.pk, content=content)
        self.assertEqual((3, 0), (result.imported, result.failed))
        self.assertEqual(
            {"De Pascale2023", "De_Pascale2023", "Plain"},
            set(Article.objects.filter(review=self.review).values_list("bibtex_key", flat=True)),
        )
        self.assertEqual(
            ["De Pascale2023: key contains spaces; the entry was kept with its original key."], result.warnings
        )

    def test_repeated_keys_are_all_imported(self):
        content = "@article{Same,\n title={First}\n}\n@article{Same,\n title={Second}\n}\n"
        result = studies.import_bibtex(review=self.review, source_id=self.source.pk, content=content)
        self.assertEqual((2, 0), (result.imported, result.failed))

    def test_entries_the_parser_drops_are_reported(self):
        parsed = studies.parse_bibtex_detailed("@article{Good,\n title={Fine}\n}\n@article{Bad,\n title={x\n")
        self.assertEqual(1 + parsed.unreadable, 2)
        self.assertTrue(any("could not be read" in warning for warning in parsed.warnings))

    def test_source_must_belong_to_review(self):
        other_source = SourceFactory()
        with self.assertRaises(NotFound):
            studies.import_bibtex(review=self.review, source_id=other_source.pk, content="@article{a, title={A}}")

    def test_empty_content(self):
        with self.assertRaises(ValidationError):
            studies.import_bibtex(review=self.review, source_id=self.source.pk, content="   ")

    def test_year_parsing(self):
        for raw, expected in (("2020", 2020), ("c. 1999", 1999), ("n.d.", None), ("", None), (None, None)):
            with self.subTest(raw=raw):
                self.assertEqual(expected, Article.parse_year(raw))


class TestArticleCrud(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.actor = cls.review.author
        cls.criteria = SelectionCriteriaFactory(review=cls.review)
        cls.other_review = ReviewFactory()
        cls.foreign_article = ArticleFactory(review=cls.other_review)

    def test_create_and_update(self):
        article = studies.create_article(
            review=self.review, source_id=self.source.pk, actor=self.actor, title="Manual entry", year="2022"
        )
        with self.subTest(msg="Test created"):
            self.assertEqual("Manual entry", article.title)
            self.assertEqual(2022, article.year_int)
            self.assertEqual(self.actor, article.created_by)

        updated = studies.update_article(
            review=self.review,
            article_id=article.pk,
            actor=self.actor,
            status=Article.ACCEPTED,
            selection_criteria_id=self.criteria.pk,
            comments="relevant",
        )
        with self.subTest(msg="Test updated"):
            self.assertEqual(Article.ACCEPTED, updated.status)
            self.assertEqual(self.criteria, updated.selection_criteria)
            self.assertEqual("relevant", updated.comments)

    def test_unknown_field_and_too_long(self):
        with self.assertRaises(ValidationError):
            studies.create_article(review=self.review, source_id=self.source.pk, bogus="x")
        with self.assertRaises(ValidationError):
            studies.create_article(review=self.review, source_id=self.source.pk, doi="x" * 51)

    def test_invalid_status(self):
        article = ArticleFactory(review=self.review, source=self.source)
        with self.assertRaises(ValidationError):
            studies.update_article(review=self.review, article_id=article.pk, status="X")

    def test_scoping(self):
        with self.subTest(msg="update article of another review"):
            with self.assertRaises(NotFound):
                studies.update_article(review=self.review, article_id=self.foreign_article.pk, title="hack")
        with self.subTest(msg="criteria of another review"):
            article = ArticleFactory(review=self.review, source=self.source)
            foreign_criteria = SelectionCriteriaFactory(review=self.other_review)
            with self.assertRaises(NotFound):
                studies.update_article(
                    review=self.review, article_id=article.pk, selection_criteria_id=foreign_criteria.pk
                )
        with self.subTest(msg="delete across reviews is refused entirely"):
            article = ArticleFactory(review=self.review, source=self.source)
            with self.assertRaises(NotFound):
                studies.delete_articles(review=self.review, article_ids=[article.pk, self.foreign_article.pk])
            self.assertTrue(Article.objects.filter(pk=article.pk).exists())

    def test_set_status_bulk(self):
        articles = ArticleFactory.create_batch(3, review=self.review, source=self.source)
        count = studies.set_status(
            review=self.review,
            article_ids=[a.pk for a in articles[:2]],
            status=Article.REJECTED,
            selection_criteria_id=self.criteria.pk,
            comments="out of scope",
            actor=self.actor,
        )
        self.assertEqual(2, count)
        statuses = list(
            Article.objects.filter(pk__in=[a.pk for a in articles]).order_by("pk").values_list("status", flat=True)
        )
        self.assertEqual([Article.REJECTED, Article.REJECTED, Article.UNCLASSIFIED], statuses)
        rejected = Article.objects.get(pk=articles[0].pk)
        self.assertEqual(
            (self.criteria, "out of scope", self.actor),
            (rejected.selection_criteria, rejected.comments, rejected.updated_by),
        )

    def test_list_articles_filters(self):
        other_source = SourceFactory()
        self.review.sources.add(other_source)
        ArticleFactory(review=self.review, source=self.source, title="Alpha study", status=Article.ACCEPTED)
        ArticleFactory(review=self.review, source=other_source, title="Beta study", status=Article.REJECTED)
        with self.subTest(msg="by source"):
            self.assertEqual(1, studies.list_articles(self.review, source_id=other_source.pk).count())
        with self.subTest(msg="by status"):
            self.assertEqual("Alpha study", studies.list_articles(self.review, status="A").get().title)
        with self.subTest(msg="by query"):
            self.assertEqual("Beta study", studies.list_articles(self.review, query="beta").get().title)

    def test_list_articles_orders_by_any_column(self):
        c = ArticleFactory(review=self.review, source=self.source, title="C", year="2019", journal="", status="U")
        ArticleFactory(review=self.review, source=self.source, title="A", year="2021", journal="TSE", status="R")
        ArticleFactory(review=self.review, source=self.source, title="B", year=None, journal="EMSE", status="A")
        studies.set_starred(review=self.review, article_id=c.pk, starred=True)

        def titles(order):
            return [article.title for article in studies.list_articles(self.review, order=order)]

        for order, expected in (
            (None, ["A", "B", "C"]),
            ("-title", ["C", "B", "A"]),
            ("year", ["C", "A", "B"]),  # no year: last
            ("-year", ["A", "C", "B"]),  # last either way
            ("journal", ["B", "A", "C"]),  # an empty journal goes with the missing ones
            ("star", ["C", "A", "B"]),  # starred first, then by title
            ("-star", ["A", "B", "C"]),
            ("status", ["B", "A", "C"]),  # A, R, U
        ):
            with self.subTest(order=order):
                self.assertEqual(expected, titles(order))
        self.assertEqual(set(studies.ORDERS) - {"ai_score"}, set(study_columns.KEYS) - {"ai_relevance"})
        with self.assertRaises(ValidationError):
            studies.list_articles(self.review, order="--title")

    def test_search_title_doi_and_bibtex_key(self):
        doi = ArticleFactory(review=self.review, source=self.source, title="One", doi="10.1145/3368089.3409741")
        key = ArticleFactory(review=self.review, source=self.source, title="Two", bibtex_key="Smith2021Screening")
        title = ArticleFactory(review=self.review, source=self.source, title="Screening with LLMs", bibtex_key="x")
        for query, expected in (
            ("10.1145/3368089", {doi}),
            ("https://doi.org/10.1145/3368089.3409741", {doi}),
            ("doi: 10.1145/3368089.3409741", {doi}),
            ("smith2021", {key}),
            ("  SCREENING ", {key, title}),
            ("nothing like it", set()),
        ):
            with self.subTest(query=query):
                self.assertEqual(expected, set(studies.list_articles(self.review, query=query)))
        self.assertEqual(3, studies.list_articles(self.review, query="   ").count())


class TestClearArticles(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.wrong, cls.right = SourceFactory(), SourceFactory()
        cls.review = ReviewFactory(sources=[cls.wrong, cls.right])

    def test_clear_deletes_only_that_source(self):
        ArticleFactory.create_batch(3, review=self.review, source=self.wrong)
        keep = ArticleFactory(review=self.review, source=self.right)
        other_review = ReviewFactory(sources=[self.wrong])
        foreign = ArticleFactory(review=other_review, source=self.wrong)
        self.assertEqual(3, studies.clear_articles(review=self.review, source_id=self.wrong.pk))
        self.assertEqual({keep.pk}, set(self.review.article_set.values_list("pk", flat=True)))
        self.assertTrue(Article.objects.filter(pk=foreign.pk).exists())
        self.assertTrue(self.review.sources.filter(pk=self.wrong.pk).exists())

    def test_clear_by_status(self):
        ArticleFactory(review=self.review, source=self.wrong, status=Article.REJECTED)
        kept = ArticleFactory(review=self.review, source=self.wrong, status=Article.ACCEPTED)
        self.assertEqual(1, studies.clear_articles(review=self.review, source_id=self.wrong.pk, status="R"))
        self.assertEqual([kept.pk], list(self.review.article_set.values_list("pk", flat=True)))
        with self.assertRaises(ValidationError):
            studies.clear_articles(review=self.review, source_id=self.wrong.pk, status="Z")

    def test_source_of_another_review_is_refused(self):
        with self.assertRaises(NotFound):
            studies.clear_articles(review=self.review, source_id=SourceFactory().pk)


class TestDuplicates(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source])
        cls.a1 = ArticleFactory(review=cls.review, source=cls.source, title="Tool Support for Mapping")
        cls.a2 = ArticleFactory(review=cls.review, source=cls.source, title="tool support for mapping")
        cls.a3 = ArticleFactory(review=cls.review, source=cls.source, title="Tool support for mapping!")
        cls.unique = ArticleFactory(review=cls.review, source=cls.source, title="Something else")

    def test_find_duplicates_groups_by_slug(self):
        groups = studies.find_duplicates(self.review)
        self.assertEqual(1, len(groups))
        self.assertEqual([self.a1.pk, self.a2.pk, self.a3.pk], [a.pk for a in groups[0]])

    def test_dash_variants_with_the_same_doi_are_duplicates(self):
        review = ReviewFactory(sources=[self.source])
        a = ArticleFactory(review=review, source=self.source, title="Navigation Using CNN-SSD", doi="10.1109/X.1")
        b = ArticleFactory(
            review=review, source=self.source, title="Navigation Using CNN\u2013SSD", doi="https://doi.org/10.1109/X.1"
        )
        groups, conflicts = studies.duplicate_report(review)
        self.assertEqual([[a.pk, b.pk]], [[x.pk for x in g.articles] for g in groups])
        self.assertEqual(("doi+title", False), (groups[0].match, groups[0].needs_review))
        self.assertEqual([], conflicts)

    def test_doi_escapes_and_prefixes_are_ignored(self):
        self.assertEqual("10.1007/978-3-031-70518-2_12", studies.normalize_doi("10.1007/978-3-031-70518-2\\_12"))
        self.assertEqual("10.1/a&b", studies.normalize_doi(" DOI: 10.1/A\\&B. "))
        self.assertEqual("10.1/x", studies.normalize_doi("https://dx.doi.org/10.1/X"))
        self.assertIsNone(studies.normalize_doi("  "))

    def test_external_link_is_the_url_or_else_the_doi(self):
        cases = [
            ("https://example.org/paper", "10.1/x", "https://example.org/paper"),
            ("", "10.1007/978-3-031-70518-2\\_12", "https://doi.org/10.1007/978-3-031-70518-2_12"),
            (None, "https://dx.doi.org/10.1145/ABC.123.", "https://doi.org/10.1145/ABC.123"),  # case kept
            (
                "  ",
                "doi: 10.1002/(SICI)1097-4571(199806)49:8<693::AID-ASI4>3.0.CO;2-0",
                "https://doi.org/10.1002/(SICI)1097-4571(199806)49:8%3C693::AID-ASI4%3E3.0.CO;2-0",
            ),
            ("javascript:alert(1)", "10.1/x", "https://doi.org/10.1/x"),
            ("javascript:alert(1)", "", None),
            (None, None, None),
        ]
        for url, doi, expected in cases:
            with self.subTest(url=url, doi=doi):
                self.assertEqual(expected, Article(url=url, doi=doi).external_url)

    def test_via_capes_is_the_doi_or_else_the_url_through_the_proxy(self):
        proxy = "ez99.periodicos.capes.gov.br"
        cases = [
            ("https://www.scopus.com/record/1", "10.1109/X.1", f"https://doi-org.{proxy}/10.1109/X.1"),
            ("https://www.scopus.com/record/1", "", f"https://www-scopus-com.{proxy}/record/1"),
            (f"https://doi-org.{proxy}/10.1145/1", "", f"https://doi-org.{proxy}/10.1145/1"),
            ("https://www.e-periodica.ch/1", None, None),
            ("javascript:alert(1)", "", None),
            (None, None, None),
        ]
        for url, doi, expected in cases:
            with self.subTest(url=url, doi=doi):
                self.assertEqual(expected, Article(url=url, doi=doi).access_url(proxy))
        self.assertIsNone(Article(url="https://example.org/1", doi="10.1/x").access_url(None))

    def test_wos_and_scopus_dois_differing_by_an_escape_are_duplicates(self):
        review = ReviewFactory(sources=[self.source])
        wos = ArticleFactory(review=review, source=self.source, title="A study", doi="10.1007/978-3-031-70518-2\\_12")
        scopus = ArticleFactory(review=review, source=self.source, title="A study", doi="10.1007/978-3-031-70518-2_12")
        groups, conflicts = studies.duplicate_report(review)
        self.assertEqual([[wos.pk, scopus.pk]], [[a.pk for a in g.articles] for g in groups])
        self.assertEqual(([], False), (conflicts, groups[0].needs_review))

    def test_title_variants_with_the_same_doi_stay_grouped_without_review_flag(self):
        variants = (
            ("Body Acupoint Localization and Visualization", "Body Acupoint Localiz.ation and Visualization"),
            (
                "Engaging recently incarcerated and gang affiliated Black and Latino/a young adults",
                "Engaging recently incarcerated and gang afiliated Black and Latino/a young adults.",
            ),
            (
                "Leveraging Ultra-Low-Power Wearables Using Distributed Neural Networks",
                "Leveraging Ultra-Law-Power Wearables Using Distributed Neural Networks",
            ),
            (
                "Moir{\\'e}Mop: Lightweight and Pervasive Moir{\\'e} Removal",
                "Moir\u00e9Mop: Lightweight and Pervasive Moir\u00e9 Removal",
            ),
            (
                "OCOsense\u2122 Smart Glasses for Analyzing Facial Expressions",
                "OCOsenseTMSmart Glasses for Analyzing Facial Expressions",
            ),
            (
                "Observation of memory effects in 5CB/PVAc liquid crystal-polymer",
                "Observation of memory effects in 5CB/PVAc liquid crystal-polymer composites",
            ),
        )
        for index, (first, second) in enumerate(variants):
            with self.subTest(title=first):
                review = ReviewFactory(sources=[self.source])
                doi = f"10.1/variant{index}"
                ArticleFactory(review=review, source=self.source, title=first, doi=doi)
                ArticleFactory(review=review, source=self.source, title=second, doi=doi)
                groups, conflicts = studies.duplicate_report(review)
                self.assertEqual((1, [], False), (len(groups), conflicts, groups[0].needs_review))
                self.assertEqual(1, len(studies.resolve_duplicates(review=review)))

    def test_one_source_without_doi_joins_the_group_by_title(self):
        review = ReviewFactory(sources=[self.source])
        title = "Smart Glasses Integrating Bone Conduction and Real-Time Image Processing"
        wos = ArticleFactory(review=review, source=self.source, title=title, year="2024")
        scopus = ArticleFactory(review=review, source=self.source, title=title, year="2024", doi="10.23919/X.1")
        ieee = ArticleFactory(review=review, source=self.source, title=title, year="2024", doi="10.23919/x.1")
        groups, conflicts = studies.duplicate_report(review)
        self.assertEqual([[wos.pk, scopus.pk, ieee.pk]], [[a.pk for a in g.articles] for g in groups])
        self.assertEqual([], conflicts)

    def test_dash_variants_without_doi_match_by_title(self):
        review = ReviewFactory(sources=[self.source])
        ArticleFactory(review=review, source=self.source, title="CNN-SSD")
        ArticleFactory(review=review, source=self.source, title="CNN\u2013SSD")
        self.assertEqual(1, len(studies.find_duplicates(review)))

    def test_same_title_with_different_dois_is_a_conflict_not_a_group(self):
        review = ReviewFactory(sources=[self.source])
        ArticleFactory(review=review, source=self.source, title="Same title", doi="10.1/a")
        ArticleFactory(review=review, source=self.source, title="Same title", doi="10.1/b")
        groups, conflicts = studies.duplicate_report(review)
        self.assertEqual([], groups)
        self.assertEqual(1, len(conflicts))
        self.assertIn("10.1/a", conflicts[0].reason)
        self.assertEqual([], studies.resolve_duplicates(review=review))

    def test_same_doi_with_different_titles_needs_review_and_is_not_auto_resolved(self):
        review = ReviewFactory(sources=[self.source])
        ArticleFactory(review=review, source=self.source, title="Edge computing for smart glasses", doi="10.1/z")
        ArticleFactory(review=review, source=self.source, title="A survey of wine tasting", doi="10.1/Z")
        groups, _ = studies.duplicate_report(review)
        self.assertEqual((1, "doi", True), (len(groups), groups[0].match, groups[0].needs_review))
        self.assertEqual([], studies.resolve_duplicates(review=review))
        self.assertEqual(1, len(studies.find_duplicates(review)))

    def test_articles_without_title_or_doi_are_not_grouped(self):
        review = ReviewFactory(sources=[self.source])
        ArticleFactory(review=review, source=self.source, title="")
        ArticleFactory(review=review, source=self.source, title="")
        self.assertEqual([], studies.find_duplicates(review))

    def test_resolve_all_keeps_oldest(self):
        marked = studies.resolve_duplicates(review=self.review)
        self.assertEqual({self.a2.pk, self.a3.pk}, {a.pk for a in marked})
        self.a1.refresh_from_db()
        self.assertEqual(Article.UNCLASSIFIED, self.a1.status)
        self.assertEqual([], studies.find_duplicates(self.review))

    def test_resolve_specific(self):
        studies.resolve_duplicates(review=self.review, article_ids=[self.a3.pk])
        self.a3.refresh_from_db()
        self.assertEqual(Article.DUPLICATED, self.a3.status)
        self.assertEqual(1, len(studies.find_duplicates(self.review)))

    def test_resolve_foreign_article(self):
        foreign = ArticleFactory()
        with self.assertRaises(NotFound):
            studies.resolve_duplicates(review=self.review, article_ids=[foreign.pk])


class TestSelectedIds(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.source = SourceFactory()
        cls.other_source = SourceFactory()
        cls.review = ReviewFactory(sources=[cls.source, cls.other_source])
        cls.match = ArticleFactory(review=cls.review, source=cls.source, title="Agents at work")
        cls.starred = ArticleFactory(review=cls.review, source=cls.source, title="Agents, starred")
        cls.starred.starred_at = cls.starred.created_at
        cls.starred.save()
        cls.accepted = ArticleFactory(review=cls.review, source=cls.source, title="Agents accepted", status="A")
        cls.elsewhere = ArticleFactory(review=cls.review, source=cls.other_source, title="Agents elsewhere")

    def test_ids_or_every_study_that_matches(self):
        self.assertEqual([self.match.pk], studies.selected_ids(self.review, ids=[self.match.pk]))
        every = studies.selected_ids(self.review, all_matching=True)
        self.assertEqual({self.match.pk, self.starred.pk, self.accepted.pk, self.elsewhere.pk}, set(every))
        matching = studies.selected_ids(
            self.review, all_matching=True, source_id=self.source.pk, status="U", query="agents"
        )
        self.assertEqual({self.match.pk, self.starred.pk}, set(matching))
        starred = studies.selected_ids(self.review, all_matching=True, starred=True)
        self.assertEqual([self.starred.pk], starred)

    def test_refused(self):
        with self.assertRaisesMessage(ValidationError, "not both"):
            studies.selected_ids(self.review, ids=[self.match.pk], all_matching=True)
        with self.assertRaisesMessage(ValidationError, "Give the studies' ids"):
            studies.selected_ids(self.review)
        with self.assertRaises(NotFound):
            studies.selected_ids(self.review, all_matching=True, source_id=SourceFactory().pk)
        with self.assertRaises(ValidationError):
            studies.selected_ids(self.review, all_matching=True, status="Z")
