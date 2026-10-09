import pytest

from resume_tailor.latex import UnsupportedCharacter, escape, to_text
from resume_tailor.naming import clean_component, folder_name, pdf_names, unique_folder
from resume_tailor.text import contains_term, extract_numbers, fold, slug_ascii, tr_lower

# ---- Turkish-aware folding and keyword matching -------------------------------------


@pytest.mark.parametrize("a,b", [
    ("İSTANBUL", "istanbul"), ("Istanbul", "istanbul"), ("ıstanbul", "istanbul"),
    ("MAKİNE ÖĞRENMESİ", "makine öğrenmesi"), ("Scikit-Learn", "scikit learn"),
])
def test_fold_equates_turkish_i_and_case(a: str, b: str) -> None:
    assert fold(a) == fold(b)


def test_tr_lower_is_turkish_correct() -> None:
    assert tr_lower("IŞIK İZMİR") == "ışık izmir"


@pytest.mark.parametrize("text,term,found", [
    ("Built with C++ and C#", "C++", True),
    ("Built with C++ and C#", "C#", True),
    ("Uses .NET and Node.js", ".NET", True),
    ("Uses .NET and Node.js", "Node.js", True),
    ("Javascript developer", "Java", False),
    ("MAKİNE ÖĞRENMESİ projesi", "makine öğrenmesi", True),
    ("scikit-learn models", "Scikit learn", True),
    ("Spring Boot 3", "Spring", True),
])
def test_contains_term(text: str, term: str, found: bool) -> None:
    assert contains_term(fold(text), term) is found


# ---- numbers -------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("about 85% accuracy", {"85"}),
    ("yaklaşık %85 doğruluk", {"85"}),
    ("10,000 movies", {"10000"}),
    ("10.000 film", {"10000"}),
    ("0,85 and 0.85", {"0.85"}),
    ("1.0× and 2.0×", {"1", "2"}),
    ("500+ tests, 500'ü aşkın", {"500"}),
    ("three services", {"3"}),
    ("üç servis", {"3"}),
    ("OAuth2 and B2 English", set()),
    ("bir uygulama, one-time purchase", set()),
    ("+5:45 and +12:45", {"5", "45", "12"}),
])
def test_extract_numbers(text: str, expected: set[str]) -> None:
    assert extract_numbers(text) == expected


# ---- naming (PROMPT.md §5) ------------------------------------------------------------


@pytest.mark.parametrize("title,slug", [
    ("Veri Bilimci", "Veri_Bilimci"),
    ("Sr. iOS Developer", "Sr_iOS_Developer"),
    ("Yazılım Mühendisi (Backend)", "Yazilim_Muhendisi_Backend"),
    ("Data Scientist / ML", "Data_Scientist_ML"),
    ("İş Zekâsı Uzmanı", "Is_Zekasi_Uzmani"),
])
def test_slug(title: str, slug: str) -> None:
    assert slug_ascii(title) == slug


def test_pdf_names() -> None:
    assert pdf_names("Jane_Doe", "Veri Bilimci") == {
        "en": "Jane_Doe_Veri_Bilimci_Resume.pdf",
        "tr": "Jane_Doe_Veri_Bilimci_Ozgecmis.pdf",
    }


def test_folder_removes_windows_invalid_and_collapses_spaces() -> None:
    assert folder_name('ABC  Firm <Ltd>', 'Data: "Scientist"/ML?') == "ABC Firm Ltd - Data ScientistML"


def test_folder_keeps_turkish_letters_and_inner_dots() -> None:
    assert folder_name("Örnek Teknoloji A.Ş.", "Veri Bilimci") == "Örnek Teknoloji A.Ş. - Veri Bilimci"


def test_folder_strips_trailing_dot() -> None:
    assert folder_name("ABC", "Sr.") == "ABC - Sr"


def test_folder_without_company() -> None:
    assert folder_name(None, "Dev") == "Unknown Company - Dev"


def test_clean_component() -> None:
    assert clean_component("  a|b*c  ") == "abc"


def test_unique_folder_collisions(tmp_path):  # type: ignore[no-untyped-def]
    (tmp_path / "A - B").mkdir()
    (tmp_path / "A - B (2)").mkdir()
    assert unique_folder("A - B", tmp_path) == "A - B (3)"


# ---- LaTeX escaping -------------------------------------------------------------------


def test_escape_specials() -> None:
    assert escape(r"100% of $5 & C# a_b {x} ~ ^ \ ") == (
        r"100\% of \$5 \& C\# a\_b \{x\} \textasciitilde{} \textasciicircum{} "
        r"\textbackslash{} "
    )


def test_escape_cannot_inject_commands() -> None:
    out = escape(r"\input{/etc/passwd} \def\x{}")
    assert "\\input" not in out.replace(r"\textbackslash{}input", "")
    assert out.startswith(r"\textbackslash{}input\{")


def test_escape_dashes_and_turkish() -> None:
    assert escape("2–5 film, ığüşöç İĞÜŞÖÇ") == "2--5 film, ığüşöç İĞÜŞÖÇ"


def test_escape_rejects_untypesettable() -> None:
    with pytest.raises(UnsupportedCharacter):
        escape("emoji 🚀")


def test_to_text_round_trips_escape() -> None:
    s = "Built 3 services (REST & gRPC) for 2–5 users, 85% C#"
    assert to_text(escape(s)) == s
