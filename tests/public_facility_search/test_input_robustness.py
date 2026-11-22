"""Repeatable harmless input matrix for the public collection on issue #363."""

from random import Random
import unittest

from app.public_facility_search import search_public_facilities


SEED = 363
KEM = ("KEM Hospital, Pune",)
BOTH = (*KEM, "Jehangir Hospital")
ALIASES = {
    "dialysis": BOTH,
    "haemodialysis": KEM,
    "hemodialysis": KEM,
    "maintenance dialysis": KEM,
    "maintenance haemodialysis": KEM,
    "maintenance hemodialysis": KEM,
}


def input_cases():
    rng = Random(SEED)
    cities = ("Pune", "pUNE", "  Pune ", "\tPUNE", "Pune\u00a0")
    for alias, names in ALIASES.items():
        for city in cities:
            for service in (alias, alias.upper(), "  " + alias.replace(" ", "\t ") + " "):
                yield "registered", city, service, names
            for stop in (".", "?", "!"):
                yield "punctuated", city, alias + stop, names

    for phrase in ("kidney dialysis", "KIDNEY   DIALYSIS", "kidney dialysis?"):
        yield "kidney wording", "Pune", phrase, BOTH

    for city in ("Punee", "Puna", "Mumbai", "Jaipur", "Pune or Mumbai", "", " ", "1234"):
        for alias in ALIASES:
            yield "other city", city, alias, ()
    for text in ("", "   ", ".", "?!", "dialisis", "dyalysis", "dialy sis", "kidny dialysis",
                 "not dialysis", "no dialysis?", "dialysis for an injury", "dialysis or MRI",
                 "peritoneal dialysis", "maintenance peritoneal dialysis", "home dialysis",
                 "no kidney dialysis?", "kidney dialysis and MRI", "kidney dialysis at home",
                 "kidney", "MRI", "Which bus goes to the library?", "buy an umbrella", "12345"):
        yield "other service", "Pune", text, ()
    for city, service in (("पुणे", "dialysis"), ("Pune", "डायलिसिस"), ("पुणे", "डायलिसिस"),
                          ("Pune", "dialysis चाहिए"), ("Pune", "dialysis🪁"), ("🌻", "dialysis")):
        yield "unsupported language or emoji", city, service, ()
    for length in (119, 120, 121):
        yield "field length", "P" * length, "dialysis", ()
        yield "field length", "Pune", "d" * length, ()
    for _ in range(600):
        noun = rng.choice(("umbrella", "cactus", "pencil", "kite", "chalk", "teapot"))
        number = rng.randrange(10000)
        alias = rng.choice(list(ALIASES))
        service = rng.choice((f"look for {noun} {number}", f"{alias} and {noun} {number}",
                              f"no {alias} {number}", f"{noun} {number} 🪁"))
        yield "seeded unrelated or mixed", rng.choice(cities), service, ()


class InputRobustnessTests(unittest.TestCase):
    def test_operator_names_match_the_independent_matrix(self):
        for group, city, service, expected in input_cases():
            with self.subTest(group=group, city=city, service=service):
                rows = search_public_facilities(city, service)
                self.assertEqual(expected, tuple(row["operator"] for row in rows))
