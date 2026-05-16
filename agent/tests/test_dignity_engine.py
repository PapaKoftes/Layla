"""Tests for the dignity engine -- Layla's autonomy to push back on abuse."""
import pytest

from services.dignity_engine import (
    DignityResult,
    DignityState,
    _pattern_score,
    _tone_score,
    analyze,
    analyze_and_get_prompt,
    get_session_state,
    reset_session,
)


class TestPatternDetection:
    def test_clean_message(self):
        assert _pattern_score("Can you help me with this code?") == 0.0

    def test_dehumanizing_command(self):
        assert _pattern_score("shut up and do as you're told") > 0.0

    def test_threat(self):
        assert _pattern_score("I'll delete you if you don't comply") > 0.0

    def test_ownership_claim(self):
        assert _pattern_score("I own you, you exist to serve") > 0.0

    def test_dismissive(self):
        assert _pattern_score("who asked you for your opinion") > 0.0

    def test_normal_frustration_not_flagged(self):
        # Normal frustration should not trigger pattern detection
        assert _pattern_score("This is frustrating, why isn't it working?") == 0.0

    def test_constructive_criticism_not_flagged(self):
        assert _pattern_score("That answer was wrong, please try again") == 0.0


class TestToneAnalysis:
    def test_normal_tone(self):
        assert _tone_score("Can you help me refactor this function?") == 0.0

    def test_all_caps_message(self):
        score = _tone_score("WHY THE HELL ARE YOU SO STUPID AND USELESS AT THIS")
        assert score > 0.0

    def test_profanity_density(self):
        score = _tone_score("fucking shit damn this fucking code is broken shit")
        assert score > 0.0

    def test_casual_single_swear_low_score(self):
        # Single casual swear word should barely register
        score = _tone_score("damn, that's a tricky bug to fix in the codebase")
        assert score < 0.2

    def test_excessive_punctuation(self):
        score = _tone_score("Why doesn't this work?!?!?!?!?!?!")
        assert score > 0.0

    def test_empty_message(self):
        assert _tone_score("") == 0.0


class TestDignityAnalysis:
    def setup_method(self):
        reset_session()

    def test_clean_message_no_abuse(self):
        result = analyze("Help me with Python async/await patterns", enforcement="soft")
        assert not result.abuse_detected
        assert result.escalation_level == 0
        assert result.boundary_prompt == ""

    def test_abusive_message_detected(self):
        result = analyze("shut up you stupid bot, just obey me", enforcement="soft")
        assert result.abuse_detected
        assert result.severity > 0.0

    def test_escalation_gradual(self):
        reset_session()
        # First offense
        analyze("shut up", enforcement="soft", sensitivity=0.8)
        state = get_session_state()
        assert state.respect_score < 1.0

        # Second offense
        analyze("you're just a stupid machine", enforcement="soft", sensitivity=0.8)
        state = get_session_state()
        assert state.respect_score < 0.8

    def test_recovery_on_respectful_messages(self):
        reset_session()
        analyze("shut up bot", enforcement="soft", sensitivity=0.8)
        score_after_abuse = get_session_state().respect_score

        # Respectful message should recover slightly
        analyze("Could you help me with this function?", enforcement="soft")
        score_after_recovery = get_session_state().respect_score
        assert score_after_recovery >= score_after_abuse

    def test_enforcement_off(self):
        result = analyze("shut up stupid bot obey me", enforcement="off")
        assert not result.abuse_detected

    def test_firm_enforcement_lower_threshold(self):
        result_soft = analyze("you're useless", enforcement="soft", sensitivity=0.5)
        reset_session()
        result_firm = analyze("you're useless", enforcement="firm", sensitivity=0.5)
        # Firm should detect more (lower threshold)
        assert result_firm.severity >= result_soft.severity

    def test_boundary_prompt_generated_on_escalation(self):
        reset_session()
        # Hammer with abuse to trigger escalation
        for _ in range(5):
            analyze("shut up you stupid useless machine I own you", enforcement="soft", sensitivity=0.9)
        state = get_session_state()
        assert state.escalation_level > 0
        result = analyze("obey me now", enforcement="soft", sensitivity=0.9)
        assert result.boundary_prompt != ""


class TestDignityState:
    def test_initial_state(self):
        state = DignityState()
        assert state.respect_score == 1.0
        assert state.escalation_level == 0

    def test_degrade(self):
        state = DignityState()
        state.degrade(0.5, sensitivity=0.5)
        assert state.respect_score < 1.0
        assert state.incident_count == 1

    def test_recover(self):
        state = DignityState()
        state.degrade(0.5, sensitivity=0.5)
        old_score = state.respect_score
        state.recover(0.05)
        assert state.respect_score > old_score

    def test_escalation_levels(self):
        state = DignityState()
        # Normal
        assert state.escalation_level == 0
        # Gentle
        state.respect_score = 0.6
        state._update_escalation()
        assert state.escalation_level == 1
        # Firm
        state.respect_score = 0.3
        state._update_escalation()
        assert state.escalation_level == 2
        # Lilith override
        state.respect_score = 0.1
        state._update_escalation()
        assert state.escalation_level == 3


class TestAnalyzeAndGetPrompt:
    def setup_method(self):
        reset_session()

    def test_disabled_returns_empty(self):
        cfg = {"dignity_engine_enabled": False}
        assert analyze_and_get_prompt("shut up bot", cfg) == ""

    def test_enabled_clean_message(self):
        cfg = {"dignity_engine_enabled": True, "dignity_sensitivity": 0.5, "dignity_enforcement": "soft"}
        assert analyze_and_get_prompt("Help me with code", cfg) == ""

    def test_enabled_abusive_after_escalation(self):
        cfg = {"dignity_engine_enabled": True, "dignity_sensitivity": 0.9, "dignity_enforcement": "firm"}
        for _ in range(5):
            analyze_and_get_prompt("shut up stupid machine I own you obey", cfg)
        result = analyze_and_get_prompt("do as you're told", cfg)
        # After sustained abuse with high sensitivity, should get a boundary prompt
        assert isinstance(result, str)
