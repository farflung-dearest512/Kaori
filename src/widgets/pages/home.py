import asyncio
import random
from gi.repository import Gtk, Adw, Gio, GObject

from ..manga import MangaOverview
from ..containers import MangaRow

from ...integrations import SourceMangaType

MAX_ROWS = 5
CANDIDATES = 15
MAX_CONCURRENT = 3
LOCAL_SOURCE_ID = "0"


@Gtk.Template(resource_path='/com/rini/kaghez/pages/home.ui')
class HomePage(Adw.NavigationPage):
    __gtype_name__ = "KaghezHomePage"

    manga_carousel = Gtk.Template.Child()
    carousel_stack = Gtk.Template.Child()
    main_box = Gtk.Template.Child()

    state = GObject.Property(type=str, default="home")

    def __init__(self):
        super().__init__()
        self.suwayomi = Gio.Application.get_default().suwayomi
        self.shown_rows = 0
        self.carousel_children = []

        self.library_handler = self.suwayomi.library.connect(
            "items-changed", self.on_library_changed
        )
        self.connect("destroy", self.on_destroy)

        asyncio.create_task(self.load())

    def on_destroy(self, *_):
        if self.library_handler is not None:
            self.suwayomi.library.disconnect(self.library_handler)
            self.library_handler = None

    async def load(self):
        try:
            await asyncio.gather(self.load_library(), self.load_sources())
        finally:
            if self.shown_rows == 0 and not self.carousel_children:
                self.state = "greeter"

    async def load_library(self):
        await self.suwayomi.refreshLibrary()
        self.sync_carousel()

    def on_library_changed(self, store, position, removed, added):
        self.sync_carousel()
        if self.carousel_children and self.state == "greeter":
            self.state = "home"

    def sync_carousel(self):
        while self.carousel_children:
            child = self.carousel_children.pop()
            self.manga_carousel.remove(child)

        for manga in list(self.suwayomi.library)[:6]:
            child = MangaOverview(manga)
            self.manga_carousel.append(child)
            self.carousel_children.append(child)

        self.carousel_stack.set_visible_child_name(
            "carousel" if self.carousel_children else "empty"
        )

    def pick_sources(self) -> list:
        eligible = [s for s in self.suwayomi.sources if str(s.id) != LOCAL_SOURCE_ID]
        by_extension = {}
        for source in eligible:
            by_extension.setdefault(source.extension_pkg_name, []).append(source)
        picked = [random.choice(group) for group in by_extension.values()]

        random.shuffle(picked)
        return picked[:CANDIDATES]

    async def load_sources(self):
        await self.suwayomi.refreshSources()
        sources = self.pick_sources()

        semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        rows_added = 0

        async def run(source):
            nonlocal rows_added
            if rows_added >= MAX_ROWS:
                return
            async with semaphore:
                if rows_added >= MAX_ROWS:
                    return
                try:
                    mangas = await self.suwayomi.getSourceManga(
                        source.id, fetch_type=SourceMangaType.POPULAR
                    )
                except Exception as e:
                    print(f"source {source.name!r} ({source.id}) failed: {e!r}")
                    return
                if not mangas or rows_added >= MAX_ROWS:
                    return

                row = MangaRow(source.name)
                row.set_items(mangas[:8])
                self.main_box.append(row)
                rows_added += 1
                self.shown_rows += 1

        await asyncio.gather(*(run(s) for s in sources), return_exceptions=True)
