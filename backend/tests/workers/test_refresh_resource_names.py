"""One canonical list of the resource names a queue entry may name (resources.py).

The refresh handler and the enqueue CLI both read it, so they cannot drift: a name the handler
understands is accepted by the CLI, and a name the CLI accepts is one the handler knows how to
treat (fetch it, or drop it uncharged)."""

from __future__ import annotations

from app.scripts import ml_publications_enqueue
from app.services.ml_publications import bundle, queue, resources
from app.workers.handlers import ml_publications as handlers


def claim_for(*names: str) -> queue.QueueClaim:
    return queue.QueueClaim("item", "MLA1", tuple(names), 0, 1, "t", 0, None)


class TestSingleSourceOfTruth:
    def test_the_cli_accepts_exactly_the_canonical_names(self) -> None:
        assert ml_publications_enqueue.KNOWN_RESOURCES is resources.REFRESH_RESOURCES

    def test_the_handler_special_names_come_from_the_same_module(self) -> None:
        assert handlers.CORE == resources.CORE_RESOURCE
        assert handlers.BUNDLE == resources.BUNDLE_RESOURCE
        assert {handlers.CORE, handlers.BUNDLE} <= set(resources.REFRESH_RESOURCES)

    def test_every_canonical_name_is_understood_by_the_handler(self) -> None:
        for name in resources.REFRESH_RESOURCES:
            plan = bundle.plan(claim_for(name).resources, [])
            fetched = name in (resources.CORE_RESOURCE, resources.BUNDLE_RESOURCE)
            assert plan.needs_core is fetched, name
            assert (name in plan.dropped) is (not fetched), name

    def test_every_default_bundle_resource_is_a_canonical_name(self) -> None:
        from app.core.config import settings

        assert set(settings.ML_PUB_BUNDLE_RESOURCES) <= set(resources.REFRESH_RESOURCES)
