"""Boundary models for generated workspace files and processor context."""

from autocli.models.boundary import (
    APPROVED_GOLDEN_VALUE_ADAPTER,
    CommandArgumentModel,
    CommandFileModel,
    CommandRequestModel,
    CommandSpecModel,
    FixtureMetaFileModel,
    FixtureRefModel,
    FixtureRequestFileModel,
    FixtureResponseFileModel,
    GoldenRefModel,
    PathShapeSegmentModel,
    ProcessorContextModel,
    ProcessorRefsModel,
    validate_approved_golden,
)

__all__ = [
    'APPROVED_GOLDEN_VALUE_ADAPTER',
    'CommandArgumentModel',
    'CommandFileModel',
    'CommandRequestModel',
    'CommandSpecModel',
    'FixtureMetaFileModel',
    'FixtureRefModel',
    'FixtureRequestFileModel',
    'FixtureResponseFileModel',
    'GoldenRefModel',
    'PathShapeSegmentModel',
    'ProcessorContextModel',
    'ProcessorRefsModel',
    'validate_approved_golden',
]
