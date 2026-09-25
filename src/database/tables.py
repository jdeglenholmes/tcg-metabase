# Python file to hold a registry of table names
from enum import Enum

class Tables(str, Enum):
    CARDS_SET_DEATILS = "card_sets"
    CARDS_CARD_DETAILS = "tcg_cards"
    CARDS_CARD_CONNECTING_GRID_DIMENSIONS = "fact_narrative_connections"
    CARDS_CARD_STORY_GRID_DIMENSIONS = "fact_physical_connections"
    ILLUSTRATORS_DETAILS = "dim_illustrator_groups"
    ILLUSTRATORS_ART_METRICS = "mv_illustrator_baseball_card"

    def __str__(self):
        return self.value