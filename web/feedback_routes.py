"""
web/feedback_routes.py — Flask Blueprint for AI/ML Feedback Loop

Routes:
  GET  /api/ai-ml/feedback/stats   — performance dashboard data
  POST /api/ai-ml/feedback/check   — trigger outcome check for OPEN trades
  POST /api/ai-ml/feedback/retrain — trigger model retrain with new data
"""
from flask import Blueprint, jsonify

feedback_bp = Blueprint("feedback", __name__)


@feedback_bp.route("/api/ai-ml/feedback/stats")
def feedback_stats():
    from ai_ml.feedback_loop import get_feedback_stats
    return jsonify(get_feedback_stats())


@feedback_bp.route("/api/ai-ml/feedback/check", methods=["POST"])
def feedback_check():
    from ai_ml.feedback_loop import check_outcomes
    return jsonify(check_outcomes())


@feedback_bp.route("/api/ai-ml/feedback/retrain", methods=["POST"])
def feedback_retrain():
    from ai_ml.feedback_loop import retrain_model
    return jsonify(retrain_model())
