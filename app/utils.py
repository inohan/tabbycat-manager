from dataclasses import dataclass
from flet.auth import OAuthProvider
from typing import TypedDict, Literal, Optional, Iterable, Callable, Any
import tabbycat_api as tc
import uuid

class MyGoogleOAuthProvider(OAuthProvider):
    """Custom Google OAuth provider which returns refresh token"""
    def __init__(self, client_id: str, client_secret: str, redirect_url: str) -> None:
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            authorization_endpoint="https://accounts.google.com/o/oauth2/auth?access_type=offline&prompt=consent",
            token_endpoint="https://oauth2.googleapis.com/token",
            redirect_url=redirect_url,
            user_scopes=[
                "https://www.googleapis.com/auth/userinfo.email",
                "https://www.googleapis.com/auth/userinfo.profile",
            ],
            user_endpoint="https://www.googleapis.com/oauth2/v3/userinfo",
            user_id_fn=lambda u: u["sub"],
            group_scopes=[],
        )

class LogoAlias(TypedDict):
    type: Literal["url", "file_id"]
    value: str

class Logo(TypedDict):
    type: Literal["alias", "url", "file_id"]
    value: str

# class LogoInfo(TypedDict):
#     aliases: dict[str, LogoAlias]
#     mappings: dict[str, Optional[list[Logo]]]

@dataclass
class LogoData:
    aliases: dict[str, LogoAlias]
    mappings: dict[str, Optional[list[Logo]]]
    
    @classmethod
    def default(cls) -> "LogoData":
        return cls(
            aliases = { #TODO: Add aliases
                
            },
            mappings = {}
        )
    
    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "LogoData|None":
        if data is None:
            return None
        return cls(aliases = data.get("aliases", None), mappings = data.get("mappings", None))
    
    def to_dict(self) -> dict:
        return {
            "aliases": self.aliases,
            "mappings": self.mappings
        }
    
    def gather_aliases(self) -> list[str]:
        aliases = {key for key in self.aliases.keys()}
        for list_logos in self.mappings.values():
            if list_logos:
                for logo in list_logos:
                    if logo["type"] == "alias":
                        aliases.add(logo["value"])
        return list(aliases)
    
    def get_object_logo(self, obj: tc.models.Team | tc.models.Adjudicator | tc.models.Speaker) -> list[Logo]|None:
        key = obj._href
        if key not in self.mappings:
            if isinstance(obj, tc.models.Team):
                self.mappings[key] = None
            elif isinstance(obj, tc.models.Adjudicator):
                self.mappings[key] = [{"type": "alias", "value": obj.institution.code}] if obj.institution else []
            elif isinstance(obj, tc.models.Speaker):
                self.mappings[key] = [{"type": "alias", "value": obj.team.institution.code}] if obj.team and obj.team.institution else []
        return self.mappings[key]

    def get_object_logo_urls(self, obj: tc.models.Team | tc.models.Adjudicator | tc.models.Speaker) -> set[str]:
        def get_url(logo: Logo) -> str|None:
            if logo["type"] == "url":
                return logo["value"]
            elif logo["type"] == "file_id":
                return f"https://drive.google.com/uc?id={logo['value']}"
            elif logo["type"] == "alias":
                alias = self.aliases.get(logo["value"], None)
                if alias is not None:
                    if alias["type"] == "url":
                        return alias["value"]
                    elif alias["type"] == "file_id":
                        return f"https://drive.google.com/uc?id={alias['value']}"
                else:
                    return None
            raise ValueError(f"Unknown logo: {logo}")
        list_logos = self.get_object_logo(obj)
        if isinstance(obj, tc.models.Team):
            if list_logos is None:
                return {url for speaker in obj.speakers for logo in self.get_object_logo(speaker) if (url := get_url(logo)) is not None}
            else:
                return {url for logo in list_logos if (url := get_url(logo)) is not None}
        elif isinstance(obj, (tc.models.Adjudicator, tc.models.Speaker)):
            assert list_logos is not None
            return {url for logo in list_logos if (url := get_url(logo)) is not None}
        raise TypeError(f"Unknown object: {obj}")

class reversor:
    def __init__(self, obj):
        self.obj = obj

    def __eq__(self, other):
        return other.obj == self.obj

    def __lt__(self, other):
        return other.obj < self.obj

def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def rank_with_ties[T](items: Iterable[T], key: Callable[[T], Any]=lambda x: x):
    # Pair items with their original indices and key values
    indexed_items = [(i, item, key(item)) for i, item in enumerate(items)]
    # Sort by key (descending)
    sorted_items = sorted(indexed_items, key=lambda x: -x[2])

    ranks = [0] * len(items)
    current_rank = 1

    for i, (idx, item, value) in enumerate(sorted_items):
        if i > 0 and value == sorted_items[i - 1][2]:
            ranks[idx] = ranks[sorted_items[i - 1][0]]  # same rank as previous
        else:
            ranks[idx] = current_rank
        current_rank = i + 2  # next available rank
    return ranks

class SlideData(TypedDict):
    texts: dict[str, str]
    images: set[str]

def create_slides(service: Any, presentation_id: str, template_slides: dict[int, str], slides: list[SlideData], position: int = 0, num_slides: Optional[int] = None):
    """Create slides

    Args:
        service (Any): Google Slides API Service
        presentation_id (str): Presentation file ID to create in
        template_slides (dict[int, str]): The template slide to use for each number of institutions
        slides (list[SlideData]): list of SlideData to create
        position (int, optional): Position to insert slide at. Defaults to 0.
    """
    # Get the total number of slides in the presentation
    if num_slides is None:
        presentation = service.presentations().get(presentationId=presentation_id).execute()
        num_slides = len(presentation["slides"])
    list_requests: list[dict] = []
    slide_uuids = []
    for slide in slides:
        slide_uuid = uuid.uuid4().hex
        slide_uuids.append(slide_uuid)
        # Duplicate slides
        list_requests.append(
            {
                "duplicateObject": {
                    "objectId": template_slides[len(slide["images"])],
                    "objectIds": {
                        template_slides[len(slide["images"])]: slide_uuid,
                    }
                }
            }
        )
        # Move slides to the end to avoid confusion when changing position later
        list_requests.append(
            {
                "updateSlidesPosition": {
                    "slideObjectIds": [slide_uuid],
                    "insertionIndex": num_slides+len(slide_uuids)
                }
            }
        )
        # Replace texts
        list_requests.extend(
            {
                "replaceAllText": {
                    "replaceText": replace_str,
                    "pageObjectIds": [slide_uuid],
                    "containsText": {
                        "text": key,
                        "matchCase": True
                    }
                }
            } for key, replace_str in slide["texts"].items()
        )
        # Replace images
        list_requests.extend(
            {
                "replaceAllShapesWithImage": {
                    "imageReplaceMethod": "CENTER_INSIDE",
                    "pageObjectIds": [slide_uuid],
                    "containsText": {
                        "text": f"{{{{image{i+1}}}}}",
                        "matchCase": True
                    },
                    "imageUrl": url
                },
            } for i, url in enumerate(slide["images"])
        )
    # Move slides to the correct position
    list_requests.append(
        {
            "updateSlidesPosition": {
                "slideObjectIds": slide_uuids,
                "insertionIndex": position
            }
        }
    )
    service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": list_requests}
    ).execute()