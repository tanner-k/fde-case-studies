"""Offline statistical layer: fitted priors and the yield model bake-off.

Nothing here runs at request time. `priors` fits the distributions the Monte
Carlo engine samples from; `yield_model` decides whether a learned quantile
model earns its place against a climatology baseline.
"""
