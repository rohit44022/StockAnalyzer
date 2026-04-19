"""
RenTech-Inspired Quant Engine for Indian Equity Markets
════════════════════════════════════════════════════════

A separate, self-contained quantitative trading system inspired by
Renaissance Technologies' Medallion Fund methodology — adapted for
NSE/BSE daily OHLCV data.

Core Principles (Jim Simons / RenTech):
  1. Statistical edge over emotion — every signal is math-backed
  2. Mean reversion at short horizons, momentum at medium horizons
  3. Regime-aware: different models for different market states
  4. Hidden Markov Models for unobservable market states
  5. Pairs / relative-value over directional bets
  6. Strict risk management: Kelly criterion, volatility targeting
  7. Signal decay awareness — alpha erodes, adapt continuously
  8. Ensemble of weak learners > single model
  9. Transaction cost & slippage modelling (India STT, brokerage)
 10. Zero tolerance for overfitting — out-of-sample validation

Modules:
  config.py        — All parameters, thresholds, Indian market constants
  statistical.py   — Core statistical models (HMM, Ornstein-Uhlenbeck,
                     Hurst exponent, cointegration, z-scores)
  signals.py       — Signal generation engine (mean-reversion, momentum,
                     microstructure, pairs, multi-factor)
  risk.py          — Portfolio optimization, Kelly sizing, drawdown control,
                     volatility targeting, correlation management
  regime.py        — Market regime detection (HMM, volatility clustering,
                     breadth, FII/DII flow proxy)
  engine.py        — Master orchestrator — runs all modules, ensembles
                     signals, produces final RenTechResult
"""

__version__ = "1.0.0"
