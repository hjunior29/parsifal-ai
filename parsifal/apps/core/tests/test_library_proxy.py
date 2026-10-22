from django.test import SimpleTestCase

from parsifal.apps.core import library_proxy
from parsifal.apps.core.exceptions import ValidationError

PROXY = "ez99.periodicos.capes.gov.br"


class TestCleanHost(SimpleTestCase):
    def test_from_what_the_user_pastes(self):
        cases = [
            (PROXY, PROXY),
            (f"  https://{PROXY}/  ", PROXY),
            (f"https://ieeexplore-ieee-org.{PROXY}/document/1234567", PROXY),
            (f"https://doi-org.{PROXY}/10.1145/3756884.3768414", PROXY),
            (f"www-sciencedirect-com.{PROXY}/science/article/pii/S1", PROXY),
            (f"https://link-springer-com-br.{PROXY}/x", PROXY),  # a country's site
            (f"HTTPS://IEEEXPLORE-IEEE-ORG.{PROXY.upper()}/x", PROXY),
            # Another library's EZproxy, including one whose own name has a hyphen.
            ("https://www-jstor-org.ezproxy.example.edu/stable/1", "ezproxy.example.edu"),
            ("https://ezproxy-prd.bodleian.ox.ac.uk/login", "ezproxy-prd.bodleian.ox.ac.uk"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, library_proxy.clean_host(value))

    def test_what_is_refused(self):
        cases = [
            ("", "Paste the address"),
            ("   ", "Paste the address"),
            ("not an address", "not a web address"),
            ("javascript:alert(1)", "not a web address"),
            ("ftp://ez99.periodicos.capes.gov.br", "not a web address"),
            ("https://localhost/", "not a web address"),
            (f"https://{PROXY}:8443/", "not a web address"),
            ("https://www.periodicos.capes.gov.br/index.php", "the CAPES portal itself"),
            ("periodicos.capes.gov.br", "the CAPES portal itself"),
        ]
        for value, message in cases:
            with self.subTest(value=value):
                with self.assertRaisesMessage(ValidationError, message):
                    library_proxy.clean_host(value)

    def test_label(self):
        self.assertEqual("Via CAPES", library_proxy.label(PROXY))
        self.assertEqual("Via proxy", library_proxy.label("ezproxy.example.edu"))


class TestProxied(SimpleTestCase):
    def test_the_address_through_the_proxy(self):
        cases = [
            ("https://doi.org/10.1109/X.1", f"https://doi-org.{PROXY}/10.1109/X.1"),
            ("https://ieeexplore.ieee.org/document/1234567", f"https://ieeexplore-ieee-org.{PROXY}/document/1234567"),
            (
                "http://www.scopus.com/inward/record.uri?eid=2-s2.0-1&origin=x#top",
                f"https://www-scopus-com.{PROXY}/inward/record.uri?eid=2-s2.0-1&origin=x#top",
            ),
            ("https://WWW.Scopus.com", f"https://www-scopus-com.{PROXY}/"),
            # Already through the proxy: kept as it is.
            (f"https://doi-org.{PROXY}/10.1145/1", f"https://doi-org.{PROXY}/10.1145/1"),
            # No link rather than a guess: hyphens of its own, a port, not a web address.
            ("https://www.e-periodica.ch/digbib/1", None),
            ("https://example.org:8080/x", None),
            ("javascript:alert(1)", None),
            ("", None),
            (None, None),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                self.assertEqual(expected, library_proxy.proxied(url, PROXY))
