from app.api.v1.spreadsheet_prompt_routing_policy import (
    SpreadsheetPromptRoute,
    SpreadsheetPromptRoutingPolicy,
)


policy = SpreadsheetPromptRoutingPolicy()


def test_explicit_no_modification_question_routes_to_assistant():
    decision = policy.decide(
        "بدون تعديل الجدول، ما هو الحساب الذي ستستخدمه إذا كان الوصف يحتوي على INSTANT PAYMENT FEES؟"
    )

    assert decision.route == SpreadsheetPromptRoute.ASSISTANT


def test_analysis_question_routes_to_assistant():
    decision = policy.decide("اذكر اسم قاعدة التسوية وكود الحساب فقط")

    assert decision.route == SpreadsheetPromptRoute.ASSISTANT


def test_explanation_question_routes_to_assistant():
    decision = policy.decide("لماذا اخترت هذا الحساب؟ اشرح السبب")

    assert decision.route == SpreadsheetPromptRoute.ASSISTANT


def test_account_change_routes_to_command_pipeline():
    decision = policy.decide("غيّر الحساب إلى 400051")

    assert decision.route == SpreadsheetPromptRoute.COMMAND


def test_delete_command_routes_to_command_pipeline():
    decision = policy.decide("احذف السطر المحدد")

    assert decision.route == SpreadsheetPromptRoute.COMMAND


def test_record_command_routes_to_command_pipeline():
    decision = policy.decide("سجل القيد في Odoo")

    assert decision.route == SpreadsheetPromptRoute.COMMAND


def test_neutral_chat_keeps_existing_pipeline():
    decision = policy.decide("مرحبا")

    assert decision.route == SpreadsheetPromptRoute.EXISTING_PIPELINE
