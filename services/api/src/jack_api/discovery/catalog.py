"""Requirement templates for the 19 task categories of Section 6.

Each category is declarative data: the questions JACK may ask (slots), their options and
defaults, which are essential, conflict rules, and what answers imply for the build
(components, external integrations, hosting). Nothing here calls a model; the engine uses this
catalogue with either Claude or local rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SlotKind = Literal["choice", "multi", "text", "bool"]
Section = Literal["overview", "features", "design", "integrations", "hosting", "constraints"]


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    keywords: tuple[str, ...] = ()          # phrases that select this option in free speech
    components: tuple[str, ...] = ()        # build components this answer adds
    integrations: tuple[str, ...] = ()      # external services this answer needs


@dataclass(frozen=True)
class Slot:
    id: str
    label: str
    question: str
    kind: SlotKind
    options: tuple[Option, ...] = ()
    default: str | tuple[str, ...] | bool | None = None
    essential: bool = True
    section: Section = "overview"
    # Ask only when an earlier answer matches: {slot_id: (allowed values...)}
    ask_if: dict[str, tuple[str, ...]] = field(default_factory=dict)
    allow_other: bool = False               # a free-text answer is kept when no option matches

    def option(self, value: str) -> Option | None:
        return next((o for o in self.options if o.value == value), None)


@dataclass(frozen=True)
class Conflict:
    """Two answers that can't both hold. Each side names the fix that keeps it."""
    a: tuple[str, str]                      # (slot, value)
    b: tuple[str, str]
    message: str
    keep_a: str                             # option label offered to keep side A
    keep_b: str
    fix_keep_a: tuple[str, str | tuple[str, ...] | None]   # (slot, new value) applied to B's slot
    fix_keep_b: tuple[str, str | tuple[str, ...] | None]   # (slot, new value) applied to A's slot


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    noun: str                               # "website", "Android app" — used in sentences
    description: str
    keywords: tuple[tuple[str, float], ...]
    slots: tuple[Slot, ...]
    base_components: tuple[str, ...]
    conflicts: tuple[Conflict, ...] = ()
    small_by_nature: bool = False           # single-deliverable jobs never need approval
    deployable: bool = False

    def slot(self, slot_id: str) -> Slot | None:
        return next((s for s in self.slots if s.id == slot_id), None)


# ------------------------------------------------------------------------------- shared slots
def _hosting(noun: str, essential: bool = True) -> Slot:
    return Slot(
        "hosting", "Hosting", f"Where should the {noun} run?", "choice",
        (
            Option("own_server", "On your own Ubuntu server",
                   ("my server", "own server", "ubuntu", "vps", "our server", "my own server"),
                   integrations=("SSH access to your Ubuntu server",)),
            Option("managed", "On a managed hosting service",
                   ("managed", "vercel", "netlify", "render", "cloud", "hosting service", "aws",
                    "azure"), integrations=("Managed hosting account",)),
            Option("local", "Only on this PC", ("this pc", "this computer", "locally", "local only",
                                                "my computer", "my laptop")),
            Option("decide_later", "Decide later", ("later", "not sure", "don't know yet")),
        ),
        default="own_server", essential=essential, section="hosting")


def _users(noun: str) -> Slot:
    return Slot(
        "users", "Users", f"Roughly how many people will use the {noun}?", "choice",
        (
            Option("few", "Just a few (under 20)", ("few", "small team", "just me", "handful",
                                                    "under 20", "5", "10")),
            Option("dozens", "Dozens to a few hundred", ("dozens", "50", "100", "hundred",
                                                         "hundreds", "medium")),
            Option("many", "Thousands or more", ("thousand", "thousands", "lots", "many",
                                                 "public", "millions"),
                   components=("Scaling and caching",)),
        ),
        default="dozens", essential=False, section="constraints")


def _auth(noun: str, default: str = "email") -> Slot:
    return Slot(
        "auth", "Sign-in", f"How should people sign in to the {noun}?", "choice",
        (
            Option("email", "E-mail and password", ("email", "password", "e-mail"),
                   components=("Authentication",), integrations=("E-mail service",)),
            Option("sso", "Company single sign-on (Microsoft or Google)",
                   ("sso", "single sign", "microsoft", "google", "azure ad", "entra", "office 365"),
                   components=("Authentication",), integrations=("Identity provider (SSO)",)),
            Option("none", "No sign-in", ("no sign", "no login", "nobody", "public", "none")),
        ),
        default=default, essential=False, section="features")


def _platform_name(noun: str) -> Slot:
    return Slot("name", "Name", f"What should the {noun} be called?", "text",
                default=None, essential=False, section="overview")


DEFAULT_PHRASES = ("you decide", "you choose", "your choice", "whatever you think",
                   "doesn't matter", "does not matter", "don't care", "do not care", "up to you",
                   "default",
                   "skip", "no preference", "anything is fine", "surprise me", "i don't mind")

# =============================================================================== categories
WEBSITE = Category(
    "website", "Website", "website",
    "Public or company websites: corporate sites, portfolios, landing pages, online shops.",
    (("website", 3), ("web site", 3), ("landing page", 3), ("homepage", 2), ("home page", 2),
     ("portfolio site", 3), ("company site", 3), ("online shop", 2), ("online store", 2),
     ("e-commerce", 2), ("ecommerce", 2), ("webpage", 2), ("site", 1), ("blog", 1)),
    (
        Slot("purpose", "Purpose", "What is the website for?", "choice",
             (Option("company", "My company or business",
                     ("company", "business", "corporate", "firm", "agency", "startup", "my company",
                      "our company", "organisation", "organization")),
              Option("shop", "Selling products online",
                     ("shop", "store", "sell", "selling", "e-commerce", "ecommerce", "products"),
                     components=("Product catalogue", "Shopping cart and checkout", "Database"),
                     integrations=("Payment provider (e.g. Stripe)",)),
              Option("personal", "Me personally (portfolio, CV, blog)",
                     ("personal", "portfolio", "myself", "cv", "resume", "my work")),
              Option("event", "An event", ("event", "conference", "wedding", "festival")),
              Option("nonprofit", "A charity or community group",
                     ("charity", "nonprofit", "non-profit", "community", "club", "church"))),
             default="company", allow_other=True),
        Slot("site_type", "Kind of site",
             "Would you like a corporate website, a customer portal or a full business platform?",
             "choice",
             (Option("corporate", "Corporate website", ("corporate", "brochure", "informational",
                                                        "company website")),
              Option("portal", "Customer portal", ("portal", "customer portal", "client portal",
                                                   "customers log in", "client area"),
                     components=("Authentication", "Customer area", "Database", "Backend API")),
              Option("platform", "Full business platform", ("platform", "full business",
                                                            "everything", "full platform"),
                     components=("Authentication", "Admin dashboard", "Database", "Backend API",
                                 "Business workflows"))),
             default="corporate", ask_if={"purpose": ("company",)}),
        Slot("business_name", "Business name", "What's the business called?", "text",
             ask_if={"purpose": ("company", "shop", "nonprofit")}),
        Slot("features", "Features", "Which of these do you need: a contact form, a blog, "
             "online booking, a newsletter, several languages, or online payments?", "multi",
             (Option("contact_form", "Contact form",
                     ("contact form", "contact", "enquiry", "inquiry"),
                     components=("Form handling",), integrations=("E-mail service",)),
              Option("blog", "Blog or news", ("blog", "news", "articles", "posts"),
                     components=("Content management",)),
              Option("booking", "Online booking", ("booking", "appointments", "reservations",
                                                   "schedule", "calendar"),
                     components=("Booking system", "Database", "Backend API"),
                     integrations=("Calendar service",)),
              Option("newsletter", "Newsletter sign-up", ("newsletter", "mailing list",
                                                          "subscribe", "mailchimp"),
                     integrations=("Newsletter service",)),
              Option("multilingual", "Several languages", ("languages", "multilingual",
                                                           "translation", "arabic", "french",
                                                           "spanish", "bilingual"),
                     components=("Translations",)),
              Option("payments", "Online payments", ("payment", "payments", "pay online",
                                                     "checkout", "stripe", "paypal"),
                     components=("Checkout", "Backend API", "Database"),
                     integrations=("Payment provider (e.g. Stripe)",)),
              Option("accounts", "User accounts", ("accounts", "login", "log in", "sign in",
                                                   "members", "membership"),
                     components=("Authentication", "Database"))),
             default=("contact_form",), section="features"),
        Slot("pages", "Pages", "Which pages should it have?", "multi",
             (Option("home", "Home", ("home",)), Option("about", "About", ("about",)),
              Option("services", "Services", ("services", "what we do")),
              Option("products", "Products", ("products", "catalogue", "catalog")),
              Option("team", "Team", ("team", "people", "staff")),
              Option("careers", "Careers", ("careers", "jobs", "hiring")),
              Option("faq", "FAQ", ("faq", "questions")),
              Option("contact", "Contact", ("contact",))),
             default=("home", "about", "services", "contact"), essential=False,
             section="features"),
        Slot("branding", "Branding", "Do you already have a logo and brand colours, "
             "or should I design them?", "choice",
             (Option("existing", "I have a logo and colours", ("have a logo", "already have",
                                                               "existing", "our logo", "yes")),
              Option("design", "Design them for me", ("design", "create", "make one", "new logo",
                                                      "don't have", "no"),
                     components=("Brand design",))),
             default="design", section="design"),
        Slot("style", "Visual style", "Any particular style — modern and minimal, bold, or "
             "classic?", "choice",
             (Option("modern", "Modern and minimal", ("modern", "minimal", "clean", "simple")),
              Option("bold", "Bold and colourful", ("bold", "colourful", "colorful", "vibrant")),
              Option("classic", "Classic and formal", ("classic", "formal", "traditional",
                                                       "elegant"))),
             default="modern", essential=False, section="design"),
        _hosting("website"),
        Slot("domain", "Domain", "Do you have a domain name already?", "choice",
             (Option("have", "Yes, I have one", ("yes", "have", "already", ".com", "we own"),
                     integrations=("DNS access for your domain",)),
              Option("need", "No, I need one", ("no", "need", "buy", "register"),
                     integrations=("Domain registrar",)),
              Option("none", "No domain for now", ("none", "not needed", "later"))),
             default="have", essential=False, section="hosting"),
    ),
    base_components=("Responsive front end", "Page content", "SEO basics"),
    conflicts=(
        Conflict(("hosting", "local"), ("features", "payments"),
                 "A site that only runs on this PC can't take payments from customers.",
                 "Keep it on this PC, without payments", "Put it online, with payments",
                 ("features", None), ("hosting", "own_server")),
        Conflict(("hosting", "local"), ("features", "booking"),
                 "A site that only runs on this PC can't take bookings from customers.",
                 "Keep it on this PC, without booking", "Put it online, with booking",
                 ("features", None), ("hosting", "own_server")),
    ),
    deployable=True,
)

WEB_APP = Category(
    "web_app", "Web application", "web application",
    "Interactive browser-based software: SaaS products, dashboards, portals, internal tools.",
    (("web app", 3), ("web application", 3), ("webapp", 3), ("saas", 3), ("dashboard", 2),
     ("portal", 2), ("internal tool", 3), ("booking system", 3), ("management system", 2),
     ("marketplace", 2), ("platform", 1), ("application", 1), ("app", 0.5)),
    (
        Slot("problem", "What it does", "What should the application help people do?", "text",
             section="overview"),
        Slot("audience", "Audience", "Is it for your own team, your customers, or the public?",
             "choice",
             (Option("internal", "My own team", ("team", "internal", "staff", "employees", "us")),
              Option("customers", "My customers", ("customers", "clients")),
              Option("public", "The general public", ("public", "anyone", "everyone"))),
             default="internal"),
        _auth("application"),
        Slot("features", "Features", "Which of these does it need: an admin dashboard, file "
             "uploads, notifications, reports, payments, or real-time updates?", "multi",
             (Option("admin", "Admin dashboard", ("admin", "dashboard", "back office"),
                     components=("Admin dashboard",)),
              Option("uploads", "File uploads", ("upload", "files", "documents", "attachments"),
                     components=("File storage",)),
              Option("notifications", "E-mail notifications", ("notification", "notify",
                                                               "email", "alerts"),
                     integrations=("E-mail service",)),
              Option("reports", "Reports and exports", ("report", "reports", "export", "charts",
                                                        "analytics"),
                     components=("Reporting",)),
              Option("payments", "Payments or subscriptions", ("payment", "payments",
                                                               "subscription", "billing",
                                                               "stripe"),
                     components=("Billing",), integrations=("Payment provider (e.g. Stripe)",)),
              Option("realtime", "Real-time updates", ("real-time", "realtime", "live", "chat"),
                     components=("Real-time messaging",))),
             default=("admin",), section="features"),
        Slot("stack", "Technology", "Any preferred technology, or shall I choose?", "choice",
             (Option("react_fastapi", "React with a Python (FastAPI) back end",
                     ("python", "fastapi", "django")),
              Option("next", "Next.js (React, full stack)", ("next", "nextjs", "next.js", "node",
                                                             "typescript", "javascript")),
              Option("dotnet", ".NET", (".net", "dotnet", "c#", "asp")),
              Option("choose", "Choose for me", ("choose", "you pick"))),
             default="choose", essential=False, section="constraints", allow_other=True),
        _users("application"),
        _hosting("application"),
    ),
    base_components=("Front end", "Backend API", "Database", "Authentication"),
    conflicts=(
        Conflict(("auth", "none"), ("features", "admin"),
                 "An admin dashboard needs people to sign in.",
                 "No sign-in, drop the admin dashboard", "Keep the admin dashboard, add sign-in",
                 ("features", None), ("auth", "email")),
        Conflict(("hosting", "local"), ("audience", "public"),
                 "An application only on this PC can't be used by the public.",
                 "Keep it on this PC, for my team", "Put it online for the public",
                 ("audience", "internal"), ("hosting", "own_server")),
    ),
    deployable=True,
)


def _mobile(cid: str, name: str, noun: str, store: str, kw: tuple[tuple[str, float], ...],
            ) -> Category:
    other_store = "the App Store" if store == "Google Play" else "Google Play"
    return Category(
        cid, name, noun, f"Native or cross-platform {noun}s, published on {store}.",
        kw,
        (
            Slot("problem", "What it does", f"What should the {noun} do?", "text"),
            Slot("platforms", "Platforms", f"Just {name.split()[0]}, or {other_store} too?",
                 "choice",
                 (Option("only", f"{name.split()[0]} only", ("only", "just", "no")),
                  Option("both", "Both Android and iOS", ("both", "too", "also", "cross",
                                                          "yes", "flutter", "react native"),
                         components=("Cross-platform build",))),
                 default="only"),
            _auth("app"),
            Slot("backend", "Online data", "Does the app need its own server for data, or can it "
                 "work entirely on the phone?", "choice",
                 (Option("server", "It needs a server", ("server", "online", "sync", "cloud",
                                                         "backend", "share")),
                         Option("offline", "Phone only", ("offline", "phone only", "on the phone",
                                                          "local", "no server"))),
                 default="server"),
            Slot("features", "Features", "Which of these: push notifications, payments, maps, "
                 "camera, or offline mode?", "multi",
                 (Option("push", "Push notifications", ("push", "notification"),
                         integrations=("Push notification service",)),
                  Option("payments", "In-app payments", ("payment", "purchase", "subscription"),
                         integrations=(f"{store} billing",)),
                  Option("maps", "Maps and location", ("map", "maps", "location", "gps"),
                         integrations=("Maps provider",)),
                  Option("camera", "Camera", ("camera", "photo", "scan")),
                  Option("offline", "Works offline", ("offline",), components=("Local storage",))),
                 default=(), section="features"),
            Slot("publish", "Publishing", f"Should I prepare it for {store}?", "bool",
                 default=True, essential=False, section="hosting"),
        ),
        base_components=("Mobile app screens", "App navigation"),
        conflicts=(
            Conflict(("backend", "offline"), ("features", "push"),
                     "Push notifications need a server to send them.",
                     "Phone only, without push notifications", "Add a server for notifications",
                     ("features", None), ("backend", "server")),
        ),
        deployable=True,
    )


ANDROID = _mobile("android_app", "Android application", "Android app", "Google Play",
                  (("android", 3), ("android app", 4), ("google play", 3), ("play store", 3),
                   ("mobile app", 1.5), ("phone app", 1.5), ("app", 0.3)))
IOS = _mobile("ios_app", "iOS application", "iPhone app", "the App Store",
              (("ios", 3), ("iphone", 3), ("ipad", 3), ("app store", 3), ("apple", 1),
               ("mobile app", 1.5), ("app", 0.3)))

WINDOWS_APP = Category(
    "windows_app", "Windows application", "Windows application",
    "Desktop software for Windows PCs.",
    (("windows app", 4), ("windows application", 4), ("desktop app", 3),
     ("desktop application", 3), ("windows program", 3), ("exe", 2), ("installer", 1),
     ("windows", 1.5), ("desktop", 1)),
    (
        Slot("problem", "What it does", "What should the program do?", "text"),
        Slot("users", "Who uses it", "Is it just for you, your team, or for anyone to download?",
             "choice",
             (Option("me", "Just me", ("me", "myself", "just me")),
              Option("team", "My team", ("team", "staff", "colleagues", "company")),
              Option("public", "Anyone", ("anyone", "public", "customers", "sell"),
                     components=("Code signing", "Auto-update"))),
             default="me"),
        Slot("data", "Data", "Does it need to share data online, or only on the PC?", "choice",
             (Option("local", "Only on the PC", ("local", "only on", "offline", "pc only")),
              Option("online", "Share online", ("online", "share", "sync", "cloud", "server"),
                     components=("Backend API", "Database"))),
             default="local"),
        Slot("stack", "Technology", "Any preferred technology, or shall I choose?", "choice",
             (Option("tauri", "Tauri (web UI + Rust)", ("tauri", "rust")),
              Option("dotnet", ".NET (WPF or WinUI)", (".net", "dotnet", "c#", "wpf", "winui")),
              Option("electron", "Electron", ("electron",)),
              Option("choose", "Choose for me", ("choose",))),
             default="choose", essential=False, section="constraints"),
    ),
    base_components=("Desktop user interface", "Windows installer"),
)

API = Category(
    "api", "API", "API",
    "Back-end services and REST/GraphQL APIs for other software to call.",
    (("api", 3), ("rest api", 4), ("graphql", 4), ("endpoint", 2), ("backend", 2),
     ("back end", 2), ("microservice", 3), ("webhook", 2), ("service", 0.5)),
    (
        Slot("problem", "What it does", "What should the API do, and who will call it?", "text"),
        Slot("style", "Style", "REST or GraphQL?", "choice",
             (Option("rest", "REST", ("rest", "json")), Option("graphql", "GraphQL", ("graphql",))),
             default="rest", essential=False, section="constraints"),
        Slot("auth", "Access control", "How should callers authenticate?", "choice",
             (Option("api_key", "API keys", ("api key", "keys", "token")),
              Option("oauth", "OAuth 2 / OpenID Connect", ("oauth", "openid", "oidc", "jwt", "sso"),
                     integrations=("Identity provider",)),
              Option("none", "No authentication (internal only)", ("none", "no auth", "internal",
                                                                   "open"))),
             default="api_key", section="features"),
        Slot("data", "Data", "Does it store its own data?", "bool", default=True),
        _users("API"),
        _hosting("API"),
    ),
    base_components=("API endpoints", "Input validation", "API documentation (OpenAPI)"),
    conflicts=(
        Conflict(("auth", "none"), ("hosting", "managed"),
                 "An API on public hosting without authentication would be open to anyone.",
                 "No authentication, keep it private", "Add API keys",
                 ("hosting", "own_server"), ("auth", "api_key")),
    ),
    deployable=True,
)


def _business(cid: str, name: str, noun: str, desc: str, kw: tuple[tuple[str, float], ...],
              modules: tuple[Option, ...], default_modules: tuple[str, ...],
              base: tuple[str, ...]) -> Category:
    return Category(
        cid, name, noun, desc, kw,
        (
            Slot("organisation", "Organisation", f"Who is the {noun} for — which company, and "
                 "what does it do?", "text"),
            Slot("modules", "Modules", "Which parts do you need? For example: "
                 + ", ".join(o.label.lower() for o in modules[:-1])
                 + f", or {modules[-1].label.lower()}.", "multi", modules,
                 default=default_modules, section="features"),
            _users(noun),
            Slot("migrate", "Existing data", "Is there existing data to bring over, such as "
                 "spreadsheets or another system?", "choice",
                 (Option("yes", "Yes, import existing data", ("yes", "excel", "spreadsheet",
                                                              "csv", "import", "existing")),
                  Option("no", "No, start fresh", ("no", "fresh", "new", "nothing"))),
                 default="no", section="integrations"),
            _auth(noun),
            _hosting(noun),
        ),
        base_components=base,
        conflicts=(
            Conflict(("auth", "none"), ("users", "many"),
                     f"A {noun} for thousands of people needs sign-in to keep data private.",
                     "No sign-in (small private use)", "Add sign-in",
                     ("users", "few"), ("auth", "email")),
        ),
        deployable=True,
    )


CRM = _business(
    "crm", "CRM", "CRM", "Customer relationship management: contacts, leads, deals, follow-ups.",
    (("crm", 5), ("customer relationship", 4), ("leads", 2), ("sales pipeline", 3),
     ("contacts", 1), ("deals", 1)),
    (Option("contacts", "Contacts and companies", ("contacts", "companies", "customers")),
     Option("pipeline", "Sales pipeline", ("pipeline", "deals", "opportunities", "sales")),
     Option("email", "E-mail tracking", ("email", "e-mail", "outlook", "gmail"),
            integrations=("Mailbox (Microsoft 365 or Gmail)",)),
     Option("tasks", "Tasks and reminders", ("tasks", "reminders", "follow-up", "follow up")),
     Option("quotes", "Quotes and invoices", ("quote", "quotes", "invoice", "invoices"),
            components=("Document generation",)),
     Option("reports", "Reports", ("report", "reports", "dashboard", "analytics"),
            components=("Reporting",))),
    ("contacts", "pipeline", "tasks"),
    ("Web front end", "Backend API", "Database", "Authentication", "Roles and permissions"))

ERP = _business(
    "erp", "ERP", "ERP system", "Enterprise resource planning: inventory, purchasing, accounting.",
    (("erp", 5), ("enterprise resource", 4), ("inventory", 2), ("purchasing", 2),
     ("procurement", 2), ("accounting system", 3), ("warehouse", 2), ("manufacturing", 2)),
    (Option("inventory", "Inventory", ("inventory", "stock", "warehouse")),
     Option("purchasing", "Purchasing", ("purchasing", "purchase", "suppliers", "procurement")),
     Option("sales", "Sales orders", ("sales", "orders")),
     Option("accounting", "Accounting", ("accounting", "finance", "ledger", "invoices"),
            components=("Accounting ledger",)),
     Option("manufacturing", "Manufacturing", ("manufacturing", "production", "bill of materials"),
            components=("Production planning",)),
     Option("reports", "Reports", ("report", "reports", "dashboard"), components=("Reporting",))),
    ("inventory", "purchasing", "sales"),
    ("Web front end", "Backend API", "Database", "Authentication", "Roles and permissions",
     "Audit trail"))

HRMS = _business(
    "hrms", "HRMS", "HR system", "Human resources: employees, leave, attendance, payroll.",
    (("hrms", 5), ("hr system", 4), ("human resources", 4), ("payroll", 3), ("leave", 1.5),
     ("attendance", 2), ("employee", 1.5), ("recruitment", 2)),
    (Option("employees", "Employee records", ("employee", "employees", "records", "staff")),
     Option("leave", "Leave requests", ("leave", "holiday", "vacation", "time off")),
     Option("attendance", "Attendance", ("attendance", "clock", "timesheet", "time sheet")),
     Option("payroll", "Payroll", ("payroll", "salary", "salaries", "wages"),
            components=("Payroll calculations",)),
     Option("recruitment", "Recruitment", ("recruit", "recruitment", "hiring", "applicants")),
     Option("reviews", "Performance reviews", ("performance", "reviews", "appraisal"))),
    ("employees", "leave", "attendance"),
    ("Web front end", "Backend API", "Database", "Authentication", "Roles and permissions",
     "Audit trail"))

TRADING = Category(
    "trading_app", "Trading application", "trading application",
    "Trading and market tools: charts, signals, portfolio tracking, order execution.",
    (("trading", 4), ("trade", 2), ("stocks", 2), ("crypto", 2), ("forex", 3), ("broker", 2),
     ("portfolio tracker", 3), ("market data", 3), ("trading bot", 4)),
    (
        Slot("markets", "Markets", "Which markets — stocks, crypto, or forex?", "multi",
             (Option("stocks", "Stocks", ("stock", "stocks", "shares", "equities")),
              Option("crypto", "Crypto", ("crypto", "bitcoin", "ethereum")),
              Option("forex", "Forex", ("forex", "fx", "currencies"))),
             default=("stocks",)),
        Slot("mode", "Trading mode", "Should it only analyse and alert, paper-trade, or place "
             "real orders?", "choice",
             (Option("analysis", "Analyse and alert only", ("analyse", "analyze", "alert",
                                                            "signals", "watch", "only")),
              Option("paper", "Paper trading (simulated)", ("paper", "simulated", "simulation",
                                                            "demo", "test")),
              Option("live", "Place real orders", ("real", "live", "execute", "place orders"),
                     components=("Order execution", "Risk limits", "Kill switch"),
                     integrations=("Brokerage or exchange API",))),
             default="analysis"),
        Slot("data_source", "Market data", "Do you have a market data or broker account to "
             "connect, or should I suggest one?", "text", default="suggest one",
             section="integrations"),
        Slot("features", "Features", "Which of these: charts, strategy back-testing, alerts, "
             "or portfolio tracking?", "multi",
             (Option("charts", "Charts", ("chart", "charts")),
              Option("backtest", "Back-testing", ("backtest", "back-test", "back testing",
                                                  "historical"),
                     components=("Back-testing engine",)),
              Option("alerts", "Alerts", ("alert", "alerts", "notify"),
                     integrations=("Notification channel",)),
              Option("portfolio", "Portfolio tracking", ("portfolio", "positions", "holdings"))),
             default=("charts", "alerts"), section="features"),
        _hosting("trading application"),
    ),
    base_components=("Market data ingestion", "Front end", "Backend", "Database"),
    conflicts=(
        Conflict(("mode", "live"), ("hosting", "decide_later"),
                 "Placing real orders needs a decided, always-on, secured host.",
                 "Keep real orders, host it on my server", "Stay on analysis only for now",
                 ("hosting", "own_server"), ("mode", "analysis")),
    ),
    deployable=True,
)

AI_PLATFORM = Category(
    "ai_platform", "AI platform", "AI platform",
    "AI-powered products: chatbots, assistants, document Q&A, agents, ML pipelines.",
    (("ai platform", 4), ("chatbot", 4), ("chat bot", 4), ("assistant", 2), ("rag", 3),
     ("llm", 3), ("machine learning", 3), ("ai agent", 4), ("gpt", 2), ("claude", 2),
     ("ai", 1.5), ("artificial intelligence", 3)),
    (
        Slot("problem", "What it does", "What should the AI do for its users?", "text"),
        Slot("knowledge", "Knowledge", "Should it answer from your own documents or data?",
             "choice",
             (Option("documents", "Yes, from our documents", ("yes", "documents", "docs", "pdf",
                                                              "knowledge base", "our data")),
                     Option("general", "No, general knowledge is fine", ("no", "general"))),
             default="documents"),
        Slot("audience", "Audience", "Is it for your team or for customers?", "choice",
             (Option("internal", "My team", ("team", "internal", "staff")),
              Option("customers", "Customers", ("customers", "public", "website visitors"))),
             default="internal"),
        Slot("model", "AI model", "Should it use Claude through your Anthropic account?", "bool",
             default=True, essential=False, section="integrations"),
        Slot("channels", "Channels", "Where will people use it — a web page, Slack or Teams, "
             "or inside another app?", "multi",
             (Option("web", "Web page", ("web", "website", "page", "browser")),
              Option("slack", "Slack", ("slack",), integrations=("Slack app",)),
              Option("teams", "Microsoft Teams", ("teams",), integrations=("Teams app",)),
              Option("api", "Inside another app (API)", ("api", "another app", "integrate"))),
             default=("web",), essential=False, section="features"),
        _hosting("AI platform"),
    ),
    base_components=("AI orchestration", "Prompting and evaluation", "Backend API",
                     "Usage and cost controls"),
    deployable=True,
)

IMAGE_GEN = Category(
    "image_generation", "Image generation", "image",
    "Creating new images: logos, illustrations, marketing graphics, product shots.",
    (("logo", 4), ("image", 2), ("picture", 2), ("illustration", 3), ("poster", 3),
     ("banner", 3), ("graphic", 2), ("icon", 2), ("generate an image", 5), ("draw", 2),
     ("artwork", 3), ("thumbnail", 3)),
    (
        Slot("subject", "Subject", "What should the image show?", "text"),
        Slot("use", "Use", "What's it for — a logo, social media, print, or a website?",
             "choice",
             (Option("logo", "Logo", ("logo", "brand")),
              Option("social", "Social media", ("social", "instagram", "facebook", "linkedin",
                                                "post")),
              Option("print", "Print", ("print", "poster", "flyer", "brochure")),
              Option("web", "Website", ("website", "web", "banner", "hero"))),
             default="web"),
        Slot("style", "Style", "Which style — photographic, illustrated, flat and minimal, "
             "or 3D?", "choice",
             (Option("photo", "Photographic", ("photo", "photographic", "realistic")),
              Option("illustration", "Illustrated", ("illustrated", "illustration", "drawn",
                                                     "cartoon")),
              Option("flat", "Flat and minimal", ("flat", "minimal", "simple", "modern")),
              Option("3d", "3D", ("3d", "three d", "render"))),
             default="flat"),
        Slot("count", "Variations", "How many variations would you like?", "choice",
             (Option("1", "One", ("one", "1", "single")),
              Option("3", "Three", ("three", "3", "few")),
              Option("6", "Six", ("six", "6", "several", "many"))),
             default="3", essential=False, section="constraints"),
    ),
    base_components=("Image generation",),
    small_by_nature=True,
)
# Integrations for creative categories depend on the image provider chosen (decision D-4).

PHOTO_EDIT = Category(
    "photo_editing", "Photo editing", "photo edit",
    "Changing existing photos: retouching, background removal, resizing, colour correction.",
    (("photo", 2), ("photos", 2), ("edit", 1.5), ("retouch", 4), ("background", 2),
     ("remove background", 5), ("remove the background", 5), ("product photos", 2),
     ("crop", 3), ("resize", 3), ("photoshop", 3), ("enhance", 2), ("colour correct", 3),
     ("color correct", 3)),
    (
        Slot("files", "Photos", "Which photos? You can say where they are, or drop them into "
             "the window.", "text"),
        Slot("edits", "Edits", "What should I do to them — remove the background, retouch, "
             "resize, or correct the colours?", "multi",
             (Option("background", "Remove background", ("background",)),
              Option("retouch", "Retouch", ("retouch", "blemish", "clean up", "touch up")),
              Option("resize", "Resize or crop", ("resize", "crop", "smaller", "size")),
              Option("colour", "Colour correction", ("colour", "color", "brightness",
                                                      "exposure", "enhance"))),
             default=("colour",)),
        Slot("output", "Output", "What format should the results be?", "choice",
             (Option("same", "Same as the originals", ("same",)),
              Option("png", "PNG", ("png", "transparent")),
              Option("jpg", "JPEG", ("jpg", "jpeg")),
              Option("webp", "WebP", ("webp",))),
             default="same", essential=False, section="constraints"),
    ),
    base_components=("Photo processing",),
    small_by_nature=True,
)

VIDEO = Category(
    "video_production", "Video production", "video",
    "Making or editing videos: promos, explainers, social clips, subtitles.",
    (("video", 4), ("film", 2), ("clip", 2), ("youtube", 3), ("reel", 3), ("tiktok", 3),
     ("subtitles", 3), ("animation", 2), ("explainer", 3), ("promo", 2)),
    (
        Slot("purpose", "Purpose", "What's the video for?", "text"),
        Slot("length", "Length", "How long — under a minute, a few minutes, or longer?",
             "choice",
             (Option("short", "Under a minute", ("short", "minute", "30 seconds", "reel",
                                                 "clip")),
              Option("medium", "A few minutes", ("few minutes", "2 minutes", "3 minutes",
                                                 "five minutes")),
              Option("long", "Longer", ("long", "longer", "10 minutes", "hour"))),
             default="short"),
        Slot("footage", "Footage", "Do you have footage to use, or should it be made from "
             "scratch?", "choice",
             (Option("have", "I have footage", ("have", "my footage", "recorded", "yes")),
              Option("scratch", "Make it from scratch", ("scratch", "no", "animation",
                                                          "generate"),
                     components=("Asset generation",))),
             default="scratch"),
        Slot("extras", "Extras", "Should it have a voice-over, music, or subtitles?", "multi",
             (Option("voiceover", "Voice-over", ("voice", "voice-over", "voiceover",
                                                 "narration")),
              Option("music", "Music", ("music", "soundtrack")),
              Option("subtitles", "Subtitles", ("subtitle", "subtitles", "captions"))),
             default=("music", "subtitles"), essential=False, section="features"),
    ),
    base_components=("Script", "Editing and rendering"),
)

INFRA = Category(
    "infrastructure", "Infrastructure management", "infrastructure work",
    "Servers, deployment, monitoring, backups, DNS, SSL — operating systems you already run.",
    (("server", 3), ("ubuntu", 3), ("infrastructure", 4), ("nginx", 3), ("docker", 3),
     ("ssl", 3), ("certificate", 2), ("backup", 3), ("monitoring", 3), ("dns", 3),
     ("deploy", 2), ("kubernetes", 3), ("diagnose", 2), ("ssh", 3), ("vps", 3)),
    (
        Slot("target", "Server", "Which server or environment is this about?", "text",
             section="hosting"),
        Slot("goal", "Goal", "What needs doing — set something up, fix a problem, monitoring, "
             "backups, or security hardening?", "choice",
             (Option("setup", "Set something up", ("set up", "setup", "install", "configure",
                                                   "deploy")),
              Option("diagnose", "Diagnose or fix a problem", ("fix", "diagnose", "problem",
                                                               "broken", "down", "slow",
                                                               "error")),
              Option("monitoring", "Monitoring", ("monitor", "monitoring", "alerts", "uptime"),
                     integrations=("Monitoring or alerting channel",)),
              Option("backups", "Backups", ("backup", "backups", "restore")),
              Option("hardening", "Security hardening", ("secure", "hardening", "firewall",
                                                         "security"))),
             default="diagnose", allow_other=True),
        Slot("changes", "Changes allowed", "May I make changes, or should I only inspect and "
             "report?", "choice",
             (Option("report", "Only inspect and report", ("only", "report", "inspect",
                                                           "read only", "don't change", "look")),
              Option("approve", "Make changes after I approve them", ("approve", "ask",
                                                                      "with approval",
                                                                      "make changes", "fix it"))),
             default="report"),
    ),
    base_components=("SSH connection with host-key verification", "Evidence collection"),
)

SECURITY = Category(
    "security_audit", "Cybersecurity audit", "security audit",
    "Reviewing systems or code for vulnerabilities, with evidence and recommendations.",
    (("security audit", 5), ("pentest", 4), ("penetration test", 4), ("vulnerability", 3),
     ("vulnerabilities", 3), ("security review", 4), ("audit", 2), ("cybersecurity", 4),
     ("hardening", 2), ("owasp", 3), ("secure", 1)),
    (
        Slot("scope", "Scope", "What should be audited — a website or app, a server, source "
             "code, or our cloud setup?", "multi",
             (Option("app", "Website or application", ("website", "app", "application", "web")),
              Option("server", "Server", ("server", "ubuntu", "vps", "host"),
                     integrations=("SSH access",)),
              Option("code", "Source code", ("code", "repository", "repo", "github"),
                     integrations=("Repository access (GitHub)",)),
              Option("cloud", "Cloud configuration", ("cloud", "aws", "azure", "gcp"),
                     integrations=("Cloud read-only access",))),
             default=("app",)),
        Slot("targets", "Targets", "Which addresses, servers or repositories exactly?", "text"),
        Slot("authorised", "Authorisation", "Do you own these systems or have written "
             "permission to test them?", "bool", default=None),
        Slot("depth", "Depth", "A passive review only, or active testing as well?", "choice",
             (Option("passive", "Passive review only", ("passive", "review", "read only",
                                                        "non-intrusive")),
              Option("active", "Active testing too", ("active", "scan", "test", "penetration"))),
             default="passive", section="constraints"),
    ),
    base_components=("Findings with evidence", "Risk ratings", "Remediation plan"),
)

RESEARCH = Category(
    "research", "Research", "research",
    "Finding, comparing and summarising information with sources.",
    (("research", 4), ("find out", 3), ("compare", 2), ("investigate", 3), ("look into", 3),
     ("analysis", 1.5), ("market research", 5), ("competitors", 3), ("summarise", 2),
     ("summarize", 2), ("what is", 1), ("which is better", 3)),
    (
        Slot("question", "Question", "What exactly should I find out?", "text"),
        Slot("depth", "Depth", "A quick answer, or a detailed report with sources?", "choice",
             (Option("quick", "Quick answer", ("quick", "short", "brief", "summary")),
              Option("report", "Detailed report", ("detailed", "report", "thorough", "deep",
                                                   "in-depth", "sources"))),
             default="quick"),
        Slot("format", "Format", "How should I give it to you?", "choice",
             (Option("spoken", "Tell me", ("tell me", "say", "speak")),
              Option("document", "A document", ("document", "doc", "report", "pdf", "word"))),
             default="document", essential=False, section="constraints"),
    ),
    base_components=("Source gathering", "Summary with citations"),
    small_by_nature=True,
)

DOCUMENTATION = Category(
    "documentation", "Documentation", "documentation",
    "Writing documents: user guides, technical docs, READMEs, proposals, policies.",
    (("documentation", 4), ("document", 2), ("docs", 3), ("readme", 4), ("manual", 3),
     ("user guide", 4), ("write up", 2), ("write a", 1.5), ("proposal", 3), ("policy", 2),
     ("specification", 2), ("report", 1)),
    (
        Slot("subject", "Subject", "What should the documentation cover?", "text"),
        Slot("audience", "Audience", "Who's it for — end users, developers, or management?",
             "choice",
             (Option("users", "End users", ("users", "customers", "end users", "staff")),
              Option("developers", "Developers", ("developers", "engineers", "technical")),
              Option("management", "Management", ("management", "executives", "board",
                                                  "managers"))),
             default="users"),
        Slot("format", "Format", "Which format — Markdown, Word, or PDF?", "choice",
             (Option("markdown", "Markdown", ("markdown", "md", "readme")),
              Option("word", "Word", ("word", "docx")),
              Option("pdf", "PDF", ("pdf",))),
             default="markdown", essential=False, section="constraints"),
        Slot("sources", "Sources", "Is there existing material I should base it on — a "
             "repository, files, or notes?", "text", default="none", essential=False,
             section="integrations"),
    ),
    base_components=("Outline", "Written content"),
    small_by_nature=True,
)

AUTOMATION = Category(
    "automation", "Automation", "automation",
    "Automating repetitive work: scripts, scheduled jobs, workflows between apps.",
    (("automate", 4), ("automation", 4), ("script", 2), ("every day", 2), ("every week", 2),
     ("schedule", 1.5), ("workflow", 2), ("zapier", 3), ("bot", 1), ("cron", 3),
     ("whenever", 1.5), ("sync", 1)),
    (
        Slot("process", "Process", "What should happen automatically, step by step?", "text"),
        Slot("trigger", "Trigger", "When should it run — on a schedule, when something "
             "happens, or when I ask?", "choice",
             (Option("schedule", "On a schedule", ("schedule", "every", "daily", "weekly",
                                                   "hourly", "night", "morning")),
              Option("event", "When something happens", ("when", "whenever", "event", "arrives",
                                                          "new email", "new file")),
              Option("manual", "When I ask", ("ask", "manual", "on demand", "command"))),
             default="manual"),
        Slot("systems", "Systems", "Which apps or systems does it touch?", "text",
             section="integrations"),
        Slot("runs_where", "Where it runs", "Should it run on this PC or on a server?", "choice",
             (Option("pc", "This PC", ("pc", "computer", "laptop", "here", "locally")),
              Option("server", "A server", ("server", "cloud", "always on"),
                     integrations=("SSH access to your Ubuntu server",))),
             default="pc", essential=False, section="hosting"),
    ),
    base_components=("Automation script", "Logging and error alerts"),
    conflicts=(
        Conflict(("trigger", "schedule"), ("runs_where", "pc"),
                 "A schedule on this PC only runs while the PC is on.",
                 "That's fine, run it on this PC", "Run it on a server",
                 ("runs_where", "pc"), ("runs_where", "server")),
    ),
)

CATEGORIES: tuple[Category, ...] = (
    WEBSITE, WEB_APP, WINDOWS_APP, ANDROID, IOS, API, CRM, ERP, HRMS, TRADING, AI_PLATFORM,
    IMAGE_GEN, PHOTO_EDIT, VIDEO, INFRA, SECURITY, RESEARCH, DOCUMENTATION, AUTOMATION,
)
BY_ID: dict[str, Category] = {c.id: c for c in CATEGORIES}
assert len(CATEGORIES) == 19 and len(BY_ID) == 19  # Section 6 lists 19 categories
