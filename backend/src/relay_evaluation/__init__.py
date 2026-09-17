"""Evaluation ground truth and verification.

EVALUATION-ONLY PACKAGE. Reads hand-authored golden manifests under ``evaluation/`` and compares
them with generated scenarios and (in later milestones) engine output. Runtime code in the
``relay`` package must never import this package.
"""
