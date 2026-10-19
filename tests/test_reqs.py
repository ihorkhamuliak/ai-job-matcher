"""Step 2b, 03.10: experience and languages. Phrases taken from live postings of the same day."""
import time

from jobbot.job import Job
from jobbot.reqs import level, marks, years


def job(title="Python Developer", seniority=(), source="justjoin"):
    return Job(source, title, "Acme", "https://x", time.time(), "PL", seniority=list(seniority))


def test_python_by_hand_and_daily_english_from_a_live_posting_and_measurement():
    """11.10: a posting the owner skipped - 'Solid Python basics...' and 'English for daily team communication' without a level.
    False positives from a measurement on 364 scored: 'coding challenges' among company events, English lessons as a benefit."""
    posting = ("Requirements - Must-haves\nSolid Python basics: data structures, functions, classes, exceptions, modules\n"
            "English sufficient for reading documentation; Polish and English for daily team communication")
    assert {"⚠️ Python руками", "⚠️ англ. щодня в команді"} <= set(marks(job(), posting))
    for line in ("minimum 1 rok komercyjnego doświadczenia w programowaniu w Pythonie", "REST API, OOP",
                 "впевнений рівень програмування на Python"):
        assert "⚠️ Python руками" in marks(job(), line), line
    benefits = ("We offer: networking events, coding challenges, and company parties.\n"
                "Lekcje angielskiego z native speakerem\nEnglish Speaking Club\nPodstawy Pythona, chęć nauki")
    assert not [m for m in marks(job(), benefits) if "Python руками" in m or "щодня" in m]
    # B2 already marked - no second English mark needed
    assert [m for m in marks(job(), "English B2 for daily communication") if "англ." in m] == ["⚠️ англ. від B2"]


# --- experience from the text

def test_years_from_english_requirements_take_the_largest():
    # DOU 03.10, Digis
    text = ("Requirements\n5+ years of professional experience with Python.\n"
            "2+ years of hands-on experience with FastAPI or Flask.\n1+ year of experience with SQL.")
    assert years(text) == 5


def test_years_polish_forms():
    assert years("Wymagania:\nmin. 2 lata doświadczenia w pracy z Pythonem") == 2
    assert years("Minimum 3 lat doświadczenia komercyjnego") == 3
    assert years("doświadczenie zawodowe: od 1 roku") == 1
    assert years("Posiadasz dwuletnie doświadczenie na podobnym stanowisku") == 2
    assert years("Masz kilkuletnie doświadczenie w IT") == 3


def test_range_takes_lower_bound():
    assert years("2-4 years of commercial experience") == 2


def test_number_without_experience_word_is_not_a_requirement():
    # 'Work with us 5 years and get a bonus' is not experience
    assert years("Jubilee bonus after 5 years in the company") is None


def test_nice_to_have_line_is_ignored():
    assert years("Nice to have: 5+ years of experience with Kubernetes") is None


def test_nice_to_have_section_is_ignored_until_next_header():
    text = ("Requirements:\n1 year of experience with Python\nNice to have\n"
            "5 years of experience with AWS\nWhat we offer:\n10 years of experience of our company")
    assert years(text) == 10  # after the 'What we offer:' header the section is required again


# --- decision 03.10: the text outweighs the field

def test_text_beats_field_both_ways():
    assert marks(job(seniority=["junior"]), "3 lata doświadczenia") == ["⚠️ стаж 3+ р."]
    assert marks(job(seniority=["senior"]), "1 year of experience in Python") == []


def test_one_year_is_clean_two_is_warning():
    assert marks(job(), "1+ year of experience") == []
    assert marks(job(), "2+ years of experience") == ["⚠️ стаж 2+ р."]


def test_without_number_level_decides():
    assert marks(job(seniority=["senior"]), "") == ["⚠️ senior, років не названо"]
    assert marks(job(seniority=["mid"]), "") == ["mid, років не названо"]
    assert marks(job(seniority=["junior"]), "") == []
    assert marks(job("Senior Data Engineer"), "") == ["⚠️ senior, років не названо"]


def test_olx_experience_required_without_number_is_soft():
    assert marks(job(seniority=["Wymagane doświadczenie"], source="olx"), "") == ["стаж просять, без цифри"]
    assert marks(job(seniority=["Bez doświadczenia"], source="olx"), "") == []


def test_several_levels_take_the_lowest():
    assert level(job(seniority=["junior/mid / Regular"])) == "low"
    assert level(job(seniority=["mid / Regular/senior"])) == "mid"


def test_djinni_months_are_years():
    assert level(job(seniority=["1+ р."], source="djinni")) == "low"
    assert level(job(seniority=["3+ р."], source="djinni")) == "high"


# --- languages

def test_english_b2_and_above_warns():
    assert "⚠️ англ. від B2" in marks(job(), "Upper-Intermediate English or higher.")
    assert "⚠️ англ. від B2" in marks(job(), "Bardzo dobra znajomość języka angielskiego")
    assert "⚠️ англ. від B2" in marks(job(), "English at B2 level")
    assert "⚠️ англ. від B2" not in marks(job(), "English B1 is enough")


def test_english_nice_to_have_not_counted():
    assert marks(job(), "Mile widziana znajomość języka angielskiego na poziomie B2") == []


def test_third_language_in_title_or_requirement_warns():
    # NFJ 03.10: Senior RPA Developer (UiPath, with German), DevOps Engineer (French)
    assert "⚠️ мова: німецька" in marks(job("Senior RPA Developer (UiPath, with German)", ["senior"]), "")
    assert "⚠️ мова: французька" in marks(job(), "Fluent French is required")
    assert "⚠️ мова: німецька" in marks(job(), "Znajomość języka niemieckiego na poziomie B2")


def test_third_language_without_requirement_word_is_not_a_requirement():
    # 'German client', 'Dutch office' are about the company, not the candidate's language
    assert marks(job(), "You will work for a German client from our Dutch office") == []


def test_polish_fluent_is_soft():
    # 19.10 (a posting scored 8/10 despite 'Native or fluent Polish'; the bank has Polish below C1): soft warning, minus 1; measured: 1 of 15 among 6+
    assert "⚠️ польська C1" in marks(job(), "Biegła znajomość języka polskiego")
    assert "⚠️ польська C1" in marks(job(), "Polish C1 or native")
    assert "⚠️ польська C1" in marks(job(), "Native or fluent Polish")


def test_strong_english_without_level_is_b2():
    # 19.10: 'Strong written and spoken English' without a level passed without a warning (measured: 9 new, 4 among 6+)
    assert "⚠️ англ. від B2" in marks(job(), "Strong written and spoken English")
    assert "⚠️ англ. від B2" in marks(job(), "Strong written communication skills in English.")
    assert "⚠️ англ. від B2" in marks(job(), "English: strong spoken and written")
    assert "⚠️ англ. від B2" not in marks(job(), "strong technical curiosity, good English communication skills")


# --- live measurement 03.10 on 62 texts

def test_glued_one_line_text_is_split_into_sentences():
    # two boards 03.10: JSON-LD without tags, headers glued to words. 'advantage' in one sentence
    # must not drop the whole text
    text = ("Document processes and performance optimization outcomesRequirements10+ years’ experience in enterprise "
            "architecture. Knowledge of Kafka is an advantage. We offer remote work.")
    assert years(text) == 10


def test_nice_header_inside_one_line_switches_off_until_next_header():
    text = "RequirementsMinimum 1 year of experience in Python. Nice to have3 years of experience with AWS. BenefitsMultisport"
    assert years(text) == 1


def test_pracuj_section_line_with_optional_header_is_nice():
    # one board: each section as one line, the first item = the header
    assert years("Our requirements, minimum 1 rok doświadczenia\nMile widziane, 4 lata doświadczenia w SAP") == 1


def test_practice_word_counts_as_experience():
    assert years("Minimum 3 lat praktyki w pracy z systemem SAP HCM") == 3


def test_ideally_is_nice():
    assert years("Ideally 3 years of experience in Banking or Treasury") is None


def test_company_age_is_not_candidate_experience():
    assert years("Jesteśmy agencją rekrutacyjną, która od 17 lat łączy pracowników z pracodawcami") is None


def test_polish_fluency_soft():
    assert "⚠️ польська C1" in marks(job(), "Professional fluency in English and Polish.")


# --- live measurement 03.10 on 176 texts

PRACUJ = ("Our requirements, minimum 4 lata doświadczenia w analizie systemowej, znajomość SQL, atutem będzie Jira\n"
          "Optional, 6 lat doświadczenia z SAP\n"
          "What we offer, karta sportowa")


def test_pracuj_comma_bullets_counted_one_by_one():
    # 'atutem bedzie Jira' in one item does not drop 'minimum 4 lata' from the same section line
    assert years(PRACUJ, "pracuj") == 4


def test_pracuj_optional_section_ends_with_its_line():
    text = "Optional, 6 lat doświadczenia z SAP\nOur requirements, 3 lata doświadczenia"
    assert years(text, "pracuj") == 3


def test_years_with_plus_count_without_experience_word():
    assert years("6+ years hands-on ML/AI engineering, with strong recent LLM product work") == 6


def test_company_age_with_ponad_is_not_experience():
    assert years("Istniejemy na rynku już ponad 10 lat.") is None


def test_company_description_with_language_is_not_requirement():
    text = "We also have 1st line support consultants who speak French and English, but also Italian and German."
    assert [m for m in marks(job(), text) if "мова" in m] == []


def test_english_b1_accepted_is_not_a_warning():
    assert "⚠️ англ. від B2" not in marks(job(), "Znajomość języka angielskiego na poziomie B1/B2")


# --- live measurement 03.10 on 275 texts

def test_abbreviation_min_does_not_cut_the_sentence():
    assert years("Doświadczenie: Min. 2 lata w analizie danych, BI lub kontrolingu") == 2


def test_similar_position_is_experience():
    assert years("Minimum 2 lata na podobnym stanowisku.") == 2


def test_nice_in_parentheses_does_not_drop_the_requirement():
    assert years("minimum 2 lata doświadczenia w branży radiokomunikacyjnej (mile widziane w sieciach TETRA)", "pracuj") == 2


def test_preferably_inside_requirement_does_not_drop_it():
    assert years("4+ years in operations/ COO role, preferably in marketing/digital") == 4


def test_glued_nice_header_without_period_is_cut_off():
    # '...with DjangoNice to have5+ years...' without a period between the item and the header
    assert years("RequirementsMinimum 1 year of experience with DjangoNice to have5+ years with AWS") == 1


# --- live measurement 03.10 on 1 039 texts: a third language

def third(text):
    return [m for m in marks(job(), text) if "мова" in m]


def test_third_language_as_alternative_to_known_one_is_not_required():
    assert third("Znajomość języka rosyjskiego lub niemieckiego") == []
    assert third("Proficiency in English or German, both written and spoken") == []


def test_market_is_not_a_language():
    assert third("firma z branży turystycznej działającej na rynku polskim i niemieckim poszukujemy senior-level eksperta") == []


def test_language_lessons_benefit_is_not_a_requirement():
    assert third("Certification opportunities English/German language lessons with native speakers") == []


def test_real_third_language_requirements_still_warn():
    assert third("Are you a tech-savvy person who speaks fluent Czech and Slovak?") == ["⚠️ мова: чеська/словацька"]
    assert third("A C1 level of Swedish") == ["⚠️ мова: шведська"]
    assert third("Very good command of Dutch (C1 level or higher)") == ["⚠️ мова: нідерландська"]


def test_language_nice_in_parentheses_or_preferred_is_not_required():
    assert third("as well as a good command of English (German language skills are an advantage)") == []
    assert third("Proficiency in English, on top proficiency in German is preferred.") == []


def test_many_alternative_languages_are_one_mark():
    text = "Additional languages - German, French, Spanish, or other European languages at B2–C1+ level."
    assert third(text) == ["⚠️ мова: німецька/французька/іспанська"]


def test_real_level_values_from_boards():
    # Measured 03.10 on all field values from the 02.10 listings
    assert level(job(seniority=["Starszy specjalista / starsza specjalistka (senior)"])) == "high"
    assert level(job(seniority=["Młodszy specjalista / młodsza specjalistka (junior)"])) == "low"
    assert level(job(seniority=["Specjalista / specjalistka (mid)"])) == "mid"
    assert level(job(seniority=["Dyrektor / Dyrektorka"])) == "high"
    assert level(job(seniority=["Staż"])) == "low"
