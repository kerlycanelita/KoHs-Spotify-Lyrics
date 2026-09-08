from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


FONT_FAMILIES = (
    "Arial",
    "Inter",
    "Roboto",
    "Open Sans",
    "Lato",
    "Noto Sans",
    "Noto Serif",
    "Merriweather",
    "Merriweather Sans",
    "Libre Baskerville",
    "Lora",
    "Vollkorn",
    "Zilla Slab",
    "Montserrat",
    "Poppins",
    "Nunito",
    "Raleway",
    "DM Sans",
    "Manrope",
    "Urbanist",
    "Work Sans",
    "Rubik",
    "Lexend",
    "Space Grotesk",
    "Archivo",
    "Archivo Black",
    "Barlow",
    "Fira Sans",
    "Karla",
    "Ubuntu",
    "Cabin",
    "Cairo",
    "Oswald",
    "Bebas Neue",
    "Barlow Condensed",
    "Roboto Condensed",
    "Anton",
    "Teko",
    "Rajdhani",
    "Saira",
    "Titillium Web",
    "Fjalla One",
    "Kanit",
    "Prompt",
    "Orbitron",
    "Chakra Petch",
    "Exo 2",
    "Unbounded",
    "Syncopate",
    "Russo One",
    "Black Ops One",
    "Bungee",
    "Monoton",
    "Righteous",
    "Press Start 2P",
    "Silkscreen",
    "Jersey 10",
    "Graduate",
    "Space Mono",
    "Playfair Display",
    "Cinzel",
    "Cormorant Garamond",
    "Bitter",
    "Abril Fatface",
    "Alfa Slab One",
    "Poiret One",
    "Josefin Sans",
    "Quicksand",
    "Comfortaa",
    "Dosis",
    "Fredoka",
    "Maven Pro",
    "League Spartan",
    "Lilita One",
    "Luckiest Guy",
    "Staatliches",
    "Amatic SC",
    "Caveat",
    "Dancing Script",
    "Great Vibes",
    "Indie Flower",
    "Kaushan Script",
    "Lobster",
    "Pacifico",
    "Permanent Marker",
    "Satisfy",
    "Shadows Into Light",
    "Special Elite",
    "Yellowtail",
)

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FUNCTION_COLOR = re.compile(r"^(rgb|rgba)\((.*)\)$", re.IGNORECASE)


def validate_css_color(value: str) -> str:
    value = value.strip()
    if _HEX_COLOR.fullmatch(value):
        return value

    match = _FUNCTION_COLOR.fullmatch(value)
    if not match:
        raise ValueError("Use HEX, RGB o RGBA")

    kind, raw_values = match.groups()
    parts = [part.strip() for part in raw_values.split(",")]
    expected = 3 if kind.lower() == "rgb" else 4
    if len(parts) != expected:
        raise ValueError("Cantidad de componentes de color incorrecta")

    try:
        channels = [int(part) for part in parts[:3]]
        alpha = float(parts[3]) if expected == 4 else 1.0
    except ValueError as exc:
        raise ValueError("Los componentes RGB deben ser numéricos") from exc

    if any(channel < 0 or channel > 255 for channel in channels):
        raise ValueError("Los canales RGB deben estar entre 0 y 255")
    if not 0 <= alpha <= 1:
        raise ValueError("La transparencia RGBA debe estar entre 0 y 1")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextStyle(StrictModel):
    color: str
    font_family: Literal[*FONT_FAMILIES]
    size: int = Field(ge=8, le=120)
    weight: int = Field(ge=100, le=900, multiple_of=100)
    bold: bool = False
    italic: bool = False
    align: Literal["left", "center", "right"] = "left"
    letter_spacing: float = Field(ge=-3, le=16)
    opacity: float = Field(ge=0, le=1)
    shadow_enabled: bool = True
    shadow_color: str = "rgba(0, 0, 0, 0.6)"
    shadow_blur: int = Field(ge=0, le=40)
    outline_width: float = Field(ge=0, le=5)
    outline_color: str = "rgba(0, 0, 0, 0.75)"

    _validate_colors = field_validator("color", "shadow_color", "outline_color")(
        validate_css_color
    )


class ElementVisibility(StrictModel):
    artwork: bool = True
    title: bool = True
    artist: bool = True
    album: bool = True
    current_lyric: bool = True
    next_lyric: bool = True


class ArtworkStyle(StrictModel):
    size: int = Field(ge=40, le=300)
    offset_y: int = Field(default=0, ge=-120, le=120)
    shape: Literal["square", "rounded", "circle"] = "rounded"
    radius: int = Field(ge=0, le=80)
    border_width: int = Field(ge=0, le=12)
    border_color: str = "rgba(255, 255, 255, 0.2)"
    shadow_enabled: bool = True
    shadow_color: str = "rgba(0, 0, 0, 0.45)"
    shadow_blur: int = Field(ge=0, le=60)
    opacity: float = Field(ge=0, le=1)

    _validate_colors = field_validator("border_color", "shadow_color")(
        validate_css_color
    )


class CardStyle(StrictModel):
    enabled: bool = True
    background_color: str = "rgba(12, 16, 26, 0.78)"
    border_color: str = "rgba(255, 255, 255, 0.16)"
    border_width: int = Field(ge=0, le=10)
    radius: int = Field(ge=0, le=60)
    shadow_enabled: bool = True
    shadow_color: str = "rgba(0, 0, 0, 0.5)"
    shadow_blur: int = Field(ge=0, le=80)

    _validate_colors = field_validator(
        "background_color", "border_color", "shadow_color"
    )(validate_css_color)


class LayoutStyle(StrictModel):
    preset: Literal["horizontal", "compact", "lyrics", "vertical", "minimal"] = "horizontal"
    gap: int = Field(ge=0, le=64)
    padding: int = Field(ge=0, le=80)
    max_width: int = Field(ge=180, le=1600)
    min_height: int = Field(ge=0, le=800)
    alignment: Literal["left", "center", "right"] = "left"
    horizontal_position: Literal["left", "center", "right"] = "center"
    vertical_position: Literal["top", "center", "bottom"] = "center"
    offset_x: int = Field(ge=-800, le=800)
    offset_y: int = Field(ge=-800, le=800)
    content_offset_y: int = Field(default=0, ge=-120, le=120)
    card: CardStyle


class AnimationStyle(StrictModel):
    song: Literal[
        "fade",
        "slide_left",
        "slide_right",
        "slide_up",
        "slide_down",
        "scale",
        "blur",
        "flip",
        "none",
    ] = "fade"
    lyric: Literal["fade", "slide_up", "slide_down", "blur", "none"] = "slide_up"
    song_duration_ms: int = Field(ge=0, le=3000)
    lyric_duration_ms: int = Field(ge=0, le=2000)
    song_easing: Literal["smooth", "snappy", "linear", "bounce"] = "smooth"
    song_exit_enabled: bool = True


class TranslationStyle(StrictModel):
    enabled: bool = True
    target_language: Literal["es"] = "es"
    show_current: bool = True
    show_next: bool = False


class OverlayConfig(StrictModel):
    version: int = 3
    elements: ElementVisibility
    layout: LayoutStyle
    artwork: ArtworkStyle
    title: TextStyle
    artist: TextStyle
    album: TextStyle
    current_lyric: TextStyle
    next_lyric: TextStyle
    translated_lyric: TextStyle
    translation: TranslationStyle
    animations: AnimationStyle


def default_config() -> OverlayConfig:
    return OverlayConfig(
        elements=ElementVisibility(),
        layout=LayoutStyle(
            gap=18,
            padding=18,
            max_width=780,
            min_height=148,
            alignment="left",
            horizontal_position="center",
            vertical_position="center",
            offset_x=0,
            offset_y=0,
            content_offset_y=0,
            card=CardStyle(border_width=1, radius=20, shadow_blur=32),
        ),
        artwork=ArtworkStyle(
            size=142,
            offset_y=0,
            radius=20,
            border_width=1,
            shadow_blur=24,
            opacity=1,
        ),
        title=TextStyle(
            color="#ffffff",
            font_family="Montserrat",
            size=24,
            weight=700,
            bold=True,
            letter_spacing=-0.3,
            opacity=1,
            shadow_blur=8,
            outline_width=0,
        ),
        artist=TextStyle(
            color="#c9d4e7",
            font_family="Inter",
            size=16,
            weight=600,
            letter_spacing=0,
            opacity=1,
            shadow_blur=6,
            outline_width=0,
        ),
        album=TextStyle(
            color="#91a0b8",
            font_family="Inter",
            size=13,
            weight=400,
            letter_spacing=0.1,
            opacity=0.9,
            shadow_blur=5,
            outline_width=0,
        ),
        current_lyric=TextStyle(
            color="#ffffff",
            font_family="Poppins",
            size=27,
            weight=700,
            bold=True,
            letter_spacing=-0.35,
            opacity=1,
            shadow_blur=10,
            outline_width=0,
        ),
        next_lyric=TextStyle(
            color="#aab6ca",
            font_family="Poppins",
            size=17,
            weight=500,
            letter_spacing=0,
            opacity=0.68,
            shadow_blur=6,
            outline_width=0,
        ),
        translated_lyric=TextStyle(
            color="#d7deeb",
            font_family="Inter",
            size=13,
            weight=500,
            italic=True,
            letter_spacing=0,
            opacity=0.82,
            shadow_blur=5,
            outline_width=0,
        ),
        translation=TranslationStyle(),
        animations=AnimationStyle(song_duration_ms=420, lyric_duration_ms=260),
    )
