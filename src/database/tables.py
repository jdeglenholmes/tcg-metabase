# Python file to hold a registry of table names
from enum import Enum

class Tables(str, Enum):
    CARDS_SET_DETAILS = "card_set_details"
    CARDS_CARD_DETAILS = "cards_card_details"
    CARDS_CARD_CONNECTING_GRID_DIMENSIONS = "cards_card_connecting_grid_dimensions"
    CARDS_CARD_STORY_GRID_DIMENSIONS = "cards_card_story_grid_dimensions"
    ILLUSTRATORS_DETAILS = "illustrators_details"
    ILLUSTRATORS_ART_METRICS = "illustrators_art_metrics"
    
    def __str__(self):
        return self.value