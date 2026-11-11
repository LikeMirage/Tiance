"""Cross-client list invalidations. No message bodies, drafts, or per-token events."""
import asyncio
from contextlib import asynccontextmanager
from threading import Lock


class WorkspaceCatalogChanges:
    def __init__(self):
        self._lock = Lock()
        self._subscribers = set()

    @asynccontextmanager
    async def subscribe(self):
        queue = asyncio.Queue(maxsize=1)
        entry = (asyncio.get_running_loop(), queue)
        with self._lock:
            self._subscribers.add(entry)
        try:
            yield queue
        finally:
            with self._lock:
                self._subscribers.discard(entry)

    def publish(self, project_id=None):
        with self._lock:
            subscribers = tuple(self._subscribers)
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._offer, queue, project_id)
            except RuntimeError:
                pass

    @staticmethod
    def _offer(queue, project_id):
        item = queue.get_nowait() if not queue.empty() else {
            'kind': 'changed', 'catalog': False, 'projects': [], 'reset': False,
        }
        if project_id is None:
            item['catalog'] = True
        elif not item['reset'] and project_id not in item['projects']:
            item['projects'].append(project_id)
            if len(item['projects']) > 128:
                item.update(reset=True, projects=[])
        queue.put_nowait(item)


workspace_catalog_changes = WorkspaceCatalogChanges()


async def workspace_catalog_events():
    async with workspace_catalog_changes.subscribe() as changes:
        # Subscribe first, then reconcile: mutations during a snapshot aren't lost.
        yield {'kind': 'ready'}
        while True:
            event = await changes.get()
            await asyncio.sleep(0.15)
            if not changes.empty():
                newer = changes.get_nowait()
                event['catalog'] |= newer['catalog']
                event['reset'] |= newer['reset']
                event['projects'] = sorted(set(event['projects']) | set(newer['projects']))
                if len(event['projects']) > 128:
                    event['reset'] = True
                if event['reset']:
                    event['projects'] = []
            yield event
