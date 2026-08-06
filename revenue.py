"""AdSense revenue estimation from category RPM.

RPM (revenue per thousand views) is the creator's share after YouTube's cut.
The figures below are published industry averages by content category, not this
channel's actual numbers -- real RPM swings widely with audience geography,
season, video length, ad formats, and whether the channel is monetised at all.
Every output here is an order-of-magnitude estimate, never a statement of
earnings.
"""

from dataclasses import dataclass

DEFAULT_RPM = 4.00

# YouTube's standard category IDs -> (name, typical RPM in USD).
CATEGORY_RPM: dict[str, tuple[str, float]] = {
    "1": ("Film & Animation", 3.00),
    "2": ("Autos & Vehicles", 5.00),
    "10": ("Music", 2.00),
    "15": ("Pets & Animals", 3.00),
    "17": ("Sports", 3.00),
    "19": ("Travel & Events", 4.50),
    "20": ("Gaming", 2.50),
    "22": ("People & Blogs", 4.00),
    "23": ("Comedy", 3.00),
    "24": ("Entertainment", 3.00),
    "25": ("News & Politics", 5.00),
    "26": ("Howto & Style", 6.00),
    "27": ("Education", 7.00),
    "28": ("Science & Technology", 8.00),
    "29": ("Nonprofits & Activism", 2.00),
}


@dataclass
class RevenueEstimate:
    category_name: str
    rpm: float
    current: float
    additional_low: float
    additional_high: float

    @property
    def is_known_category(self) -> bool:
        return self.category_name != "Uncategorised"


def rpm_for(category_id: str) -> tuple[str, float]:
    """Category name and RPM. Unknown or missing categories fall back to a
    general-content average rather than guessing at zero."""
    return CATEGORY_RPM.get(str(category_id), ("Uncategorised", DEFAULT_RPM))


def estimate_revenue(
    views: int, category_id: str, additional_views_low: float = 0, additional_views_high: float = 0
) -> RevenueEstimate:
    name, rpm = rpm_for(category_id)
    per_view = rpm / 1000
    return RevenueEstimate(
        category_name=name,
        rpm=rpm,
        current=max(views, 0) * per_view,
        additional_low=max(additional_views_low, 0) * per_view,
        additional_high=max(additional_views_high, 0) * per_view,
    )
