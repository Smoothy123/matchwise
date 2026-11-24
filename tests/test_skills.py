from matchwise.skills import extract_skills, load_vocabulary


def test_vocabulary_loads_without_duplicates():
    vocab = load_vocabulary()  # raises if a term is listed twice
    assert vocab["postgres"] == "postgresql"
    assert len(set(vocab.values())) > 150


def test_aliases_map_to_one_canonical_name():
    assert extract_skills("Postgres, Node.js and K8s") == ["kubernetes", "node.js", "postgresql"]


def test_symbols_stay_part_of_the_term():
    assert extract_skills("We use C++ and C# daily") == ["c#", "c++"]


def test_no_matches_inside_longer_words():
    # 'java' in 'javascript', 'excel' in 'excellent', 'sql' in 'mysql'
    assert extract_skills("JavaScript, excellent MySQL skills") == ["javascript", "mysql"]


def test_longest_term_wins_and_line_breaks_are_ignored():
    assert extract_skills("React Native apps; machine\nlearning") == ["machine learning", "react native"]


def test_everyday_words_are_not_skills():
    assert extract_skills("Go to market fast with a swift, epic spring launch") == []


def test_links_and_emails_are_ignored():
    text = "Questions? Email Recruitment@acme.com or see https://www.dol.gov/ofccp/regs/compliance/posters"
    assert extract_skills(text) == []


def test_equal_opportunity_sentences_are_ignored():
    text = (
        "You will write Python every day. Acme is an equal opportunity employer and does not "
        "discriminate in recruitment, hiring or compliance matters. Experience with SQL is a plus."
    )
    assert extract_skills(text) == ["python", "sql"]
