"""The target's own first word must not end the acquirer capture (SSTI)."""
from main import extract_acquirer

SSTI = ("SoundThinking to be Acquired by Transom Capital Group SoundThinking shareholders to receive $8.00 per share "
        "in cash, plus one non-transferable contingent value right (CVR) for up to an additional $3.00 per share")

def test_ssti_headline_run_on():
    assert extract_acquirer(SSTI, target_name="SOUNDTHINKING, INC.") == "Transom Capital Group"

def test_names_without_a_trailing_target_word_are_untouched():
    assert extract_acquirer("American Industrial Partners to acquire Avanos Medical for $14.50 per share in an all-cash deal.",
                            target_name="Avanos Medical") == "American Industrial Partners"
    assert extract_acquirer("Smithfield Foods to acquire all of Nathan's Famous' issued and outstanding shares for $102.00 per share.",
                            target_name="Nathan's Famous") == "Smithfield Foods"

def test_no_target_name_means_no_trimming():
    assert extract_acquirer(SSTI, target_name="") == "Transom Capital Group SoundThinking"
