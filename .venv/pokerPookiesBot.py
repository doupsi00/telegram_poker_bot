import logging
import random
from treys import Evaluator, Card
from telegram import Update, ParseMode, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackContext, CallbackQueryHandler, Filters

logger = logging.getLogger(__name__)

# Game Data
game_data = {
    "buy_in": 300,
    "small_blind": 1,
    "big_blind": 2,
    "deck": [],
    "players": {},  # {player_id: {name, cards, capital, bet, folded}}
    "host": None,
    "pot": 0,
    "table": [],
    "current_player": None,
    "last_raise": 2,
    "small_blind_pos": -1,
    "game_active": False,
    "last_to_raise": None,
    "left_to_bet": 0
}

JOIN_BUTTON = "Join"

START_GAME_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton(JOIN_BUTTON, callback_data=JOIN_BUTTON)]
])

BUY_IN_MARKUP = InlineKeyboardMarkup([
    [InlineKeyboardButton(f"{i*100}", callback_data=str(i*100)) for i in range(1, 11)]
])

def start(update: Update, context: CallbackContext) -> None:
    """Starts the game setup, allows players to join."""
    global game_data
    user = update.message.from_user

    if game_data["host"] is None:
        game_data["host"] = user.id  # Assign the host

        context.bot.send_message(
            update.message.chat_id,
            "🎲 Welcome to PokerBot! Click Join button to enter the game. \nAfter everyone has joined, host can start the game by clicking /startgame",
            parse_mode=ParseMode.HTML,
            reply_markup=START_GAME_MARKUP
        )

        # Store message ID to update later
        players_message = context.bot.send_message(
            update.message.chat_id,
            "**Players:**\n",
            parse_mode=ParseMode.HTML
        )
        context.chat_data['players_message_id'] = players_message.message_id
        context.chat_data['chat_id'] = update.message.chat_id
        """
        buy_in_message = context.bot.send_message(
            update.message.chat_id,
            "💰 Please select the buy-in amount for all players:",
            parse_mode=ParseMode.HTML,
            reply_markup=BUY_IN_MARKUP
        )
        context.chat_data["buy_in_message_id"] = buy_in_message.message_id
        """
def button_tap(update: Update, context: CallbackContext) -> None:
    """Handles Join Game button tap"""
    global game_data
    query = update.callback_query
    user_id = query.from_user.id
    user_name = query.from_user.first_name

    if query.data == JOIN_BUTTON:
        if user_id not in game_data["players"]:
            game_data["players"][user_id] = {
                "name": user_name,
                "cards": [],
                "capital": 300,  # Default capital
                "bet": 0,
                "folded": False
            }

            # Retrieve stored chat ID and message ID
            chat_id = context.chat_data.get('chat_id')
            message_id = context.chat_data.get('players_message_id')

            if chat_id and message_id:
                # Update players list
                players_list = "\n".join([f"✅ {p_data['name']}" for p_data in game_data["players"].values()])
                updated_text = f"**Players:**\n{players_list}"

                # Edit the players list message
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=updated_text,
                    parse_mode=ParseMode.HTML
                )

    """else:  # Handle Buy-in Selection
        if user_id == game_data["host"]:
            game_data["buy_in"] = int(query.data)
            context.bot.delete_message(query.message.chat_id, context.chat_data["buy_in_message_id"])
            context.bot.send_message(query.message.chat_id, f"✅ Buy-in confirmed: {game_data['buy_in']}")
    """
    query.answer()  # Close query interaction

def startgame(update: Update, context: CallbackContext) -> None:
    """Starts a new round in the game, rotating small blind."""
    global game_data
    reset_round()
    user = update.message.from_user

    if user.id != game_data["host"]:
        context.bot.send_message(update.message.chat_id, "❌ Only the host can start the game.")
        return

    if len(game_data["players"]) < 2:
        context.bot.send_message(update.message.chat_id, "⚠️ At least 2 players are needed to start the game.")
        return

    game_data["game_active"] = True

    # Reset deck & shuffle
    game_data["deck"] = generate_deck()
    random.shuffle(game_data["deck"])

    # Rotate small blind position
    player_ids = list(game_data["players"].keys())
    num_players = len(player_ids)
    small_blind_index = game_data["small_blind_pos"] % num_players
    big_blind_index = (small_blind_index + 1) % num_players
    first_player_index = (big_blind_index + 1) % num_players

    small_blind_id = player_ids[small_blind_index]
    big_blind_id = player_ids[big_blind_index]


    game_data["current_player"] = player_ids[first_player_index]

    # Betting setup
    game_data["players"][small_blind_id]["bet"] = game_data["small_blind"]
    game_data["players"][small_blind_id]["capital"] -= game_data["small_blind"]
    game_data["players"][big_blind_id]["bet"] = game_data["big_blind"]
    game_data["players"][big_blind_id]["capital"] -= game_data["big_blind"]
    game_data["pot"] = game_data["small_blind"] + game_data["big_blind"]
    game_data["last_to_raise"] = big_blind_id
    game_data["left_to_bet"] = len(game_data["players"])

    # Deal cards to each player
    for player_id, player_data in game_data["players"].items():
        player_data["cards"] = [game_data["deck"].pop(), game_data["deck"].pop()]
        context.bot.send_message(player_id, f"🃏 Your hand: {player_data['cards'][0]} {player_data['cards'][1]}")

    # Announce blinds
    context.bot.send_message(update.message.chat_id, f"🎲 Round Started! {game_data['players'][small_blind_id]['name']} is Small Blind "
                                                     f"(${game_data['small_blind']}) and {game_data['players'][big_blind_id]['name']} is Big Blind "
                                                     f"(${game_data['big_blind']}).")

    send_player_turn(context, update.message.chat_id)


def fold(update: Update, context: CallbackContext):
    """Handles the player folding."""
    global game_data
    user = update.message.from_user

    if user.id != game_data["current_player"]:
        return  # Ignore if it's not the player's turn

    player = game_data["players"][user.id]
    player["folded"] = True
    game_data["left_to_bet"] -= 1

    context.bot.send_message(update.message.chat_id, f"🚪 {player['name']} folded.")
    move_to_next_player(context, update.message.chat_id)

def check(update: Update, context: CallbackContext):
    """Handles the player checking."""
    global game_data
    user = update.message.from_user

    if user.id != game_data["current_player"]:
        return  # Ignore if it's not the player's turn

    player = game_data["players"][user.id]
    last_raise = game_data["last_raise"]
    game_data["left_to_bet"] -= 1

    # Prevent checking if there's an active bet to call
    if player["bet"] < last_raise:
        context.bot.send_message(update.message.chat_id, "❌ You must call or raise to match the current bet.")
    else:
        context.bot.send_message(update.message.chat_id, f"✔ {player['name']} checked.")
        move_to_next_player(context, update.message.chat_id)



def call(update: Update, context: CallbackContext):
    """Handles the player calling the bet."""
    global game_data
    user = update.message.from_user

    if user.id != game_data["current_player"]:
        return  # Ignore if it's not the player's turn

    player = game_data["players"][user.id]
    last_raise = game_data["last_raise"]
    call_amount = last_raise - player["bet"]
    game_data["left_to_bet"] -= 1

    if player["capital"] < call_amount:
        context.bot.send_message(update.message.chat_id, "❌ You don't have enough to call.")
        return

    player["capital"] -= call_amount
    player["bet"] += call_amount
    game_data["pot"] += call_amount

    context.bot.send_message(update.message.chat_id, f"📞 {player['name']} called (${call_amount}).")

    # **Check if the betting round should end**
    active_players = [p for p in game_data["players"].values() if not p["folded"]]

    if len(active_players) == 1:
        winner_name = active_players[0]["name"]
        context.bot.send_message(update.message.chat_id, f"🏆 {winner_name} wins the round! 🎉")
        reset_round()
        return


    move_to_next_player(context, update.message.chat_id)


def raise_bet(update: Update, context: CallbackContext):
    """Handles the player raising the bet."""
    global game_data
    user = update.message.from_user
    text = update.message.text.split()

    if user.id != game_data["current_player"]:
        return  # Ignore if it's not the player's turn

    player = game_data["players"][user.id]
    active_players = [p_id for p_id, p_data in game_data["players"].items() if not p_data["folded"]]

    try:
        amount = int(text[1])
        if amount <= 0:
            context.bot.send_message(update.message.chat_id, "❌ Invalid raise amount. Must be greater than 0.")
            return
        if player["capital"] < amount:
            context.bot.send_message(update.message.chat_id, "❌ You don't have enough to raise that amount.")
            return

        game_data["last_raise"] = player["bet"] + amount
        player["capital"] -= amount
        player["bet"] += amount
        game_data["pot"] += amount
        game_data["left_to_bet"] = len(active_players)-1
        print(len(active_players))

        context.bot.send_message(update.message.chat_id,
                                 f"📈 {player['name']} raised to ${game_data['last_raise']}.")
        move_to_next_player(context, update.message.chat_id)

    except (ValueError, IndexError):
        context.bot.send_message(update.message.chat_id, "❌ Invalid format. Use /raise <amount>.")


def move_to_next_player(context: CallbackContext, chat_id):
    """Moves to the next player or advances phase if betting is complete."""
    global game_data

    # **Check if only one player remains**
    active_players = [p_id for p_id, p_data in game_data["players"].items() if not p_data["folded"]]

    if len(active_players) == 1:
        winner_id = active_players[0]
        winner_name = game_data["players"][winner_id]["name"]
        context.bot.send_message(chat_id, f"🏆 {winner_name} wins the round! 🎉")
        game_data["players"][winner_id]["capital"] += game_data["pot"]
        reset_round()
        return

    # **Track actions per round**
    print(game_data["left_to_bet"])
    if game_data["left_to_bet"] == 0:
        advance_phase(context, chat_id)
        return

    # **Rotate to the next active player**
    player_ids = list(game_data["players"].keys())
    num_players = len(player_ids)
    current_index = player_ids.index(game_data["current_player"])

    for _ in range(num_players):
        current_index = (current_index + 1) % num_players
        next_player_id = player_ids[current_index]
        if not game_data["players"][next_player_id]["folded"]:
            game_data["current_player"] = next_player_id
            send_player_turn(context, chat_id)
            return

def send_player_turn(context: CallbackContext, chat_id: int):
    """Sends message to notify the current player it's their turn with available actions."""
    player_id = game_data["current_player"]
    if not player_id or game_data["players"][player_id]["folded"]:
        move_to_next_player(context, chat_id)
        return

    last_raise = game_data["last_raise"]
    player_bet = game_data["players"][player_id]["bet"]
    player_name = game_data["players"][player_id]["name"]

    # Determine available actions
    if player_bet < last_raise:  # Player must match the raise
        actions = "/call /raise <amount> /fold"
    else:  # No previous raise, so player can check
        actions = "/check /raise <amount> /fold"

    # Display bet status of each player
    bet_info = "\n".join([
        f"{data['name']} - Bet: ${data['bet']}{' (Folded)' if data['folded'] else ''}"
        for data in game_data["players"].values()
    ])

    context.bot.send_message(
        chat_id,
        f"🎭 {player_name}, it's your turn!\n"
        f"🃏 Available Actions: {actions}\n"
        f"\n💰 Pot: ${game_data['pot']}\n"
        f"\n🔹 Current Bets:\n{bet_info}"
    )


def advance_phase(context: CallbackContext, chat_id):
    """Moves to the next phase (Flop → Turn → River → Showdown) and resets betting."""
    global game_data

    if len(game_data["table"]) == 0:  # **Reveal Flop (first 3 cards)**
        game_data["table"] = [game_data["deck"].pop() for _ in range(3)]
        context.bot.send_message(chat_id, f"🃏 Flop: {' '.join(game_data['table'])}")
    elif len(game_data["table"]) == 3:  # **Reveal Turn (4th card)**
        game_data["table"].append(game_data["deck"].pop())
        context.bot.send_message(chat_id, f"🃏 Turn: {' '.join(game_data['table'])}")
    elif len(game_data["table"]) == 4:  # **Reveal River (5th card)**
        game_data["table"].append(game_data["deck"].pop())
        context.bot.send_message(chat_id, f"🃏 River: {' '.join(game_data['table'])}")
    else:  # **Move to Showdown**
        context.bot.send_message(chat_id, "🏆 Time for showdown! Evaluating hands...")
        determine_winner(context, chat_id)
        return

    # **Reset Bets and Action Tracking for the New Betting Phase**
    for player in game_data["players"].values():
        player["bet"] = 0
    game_data["last_raise"] = 0
    game_data["left_to_bet"] = len([p_id for p_id, p_data in game_data["players"].items() if not p_data["folded"]])
    # **Start Betting Again**
    start_new_betting_round(context, chat_id)


def reset_round():
    """Resets the game state for a new round but keeps player balances."""
    global game_data

    game_data["small_blind_pos"] += 1  # Rotate blinds for next round
    game_data["deck"] = generate_deck()
    random.shuffle(game_data["deck"])
    game_data["table"] = []
    game_data["pot"] = 0
    game_data["last_raise"] = game_data["big_blind"]
    game_data["left_to_bet"] = len(game_data["players"])

    for player in game_data["players"].values():
        player["bet"] = 0
        player["folded"] = False
        player["cards"] = []


def determine_winner(context: CallbackContext, chat_id):
    """Determines the winner after the River is revealed."""
    global game_data

    active_players = [p_id for p_id, p_data in game_data["players"].items() if not p_data["folded"]]

    suits = {'♠': 's', '♥': 'h', '♣': 'c', '♦': 'd'}

    if len(active_players) == 1:
        # Only one player left, they win automatically
        winner_id = active_players[0]
        winner_name = game_data["players"][winner_id]["name"]
        context.bot.send_message(chat_id, f"🏆 {winner_name} wins the round! 🎉")
        reset_round()
        return

    # Evaluate each player's best hand using their two-hole cards + community cards
    best_hand = None
    winner_id = None

    for player_id in active_players:
        player_cards = game_data["players"][player_id]["cards"]

        combined_hand = player_cards + game_data["table"]
        combined_hand = [card.translate(str.maketrans(suits)) for card in combined_hand]
        combined_hand = [card.replace('10', 'T') for card in combined_hand]


        # Rank hand
        hand_rank = evaluate_hand(combined_hand)

        # Check if it's the best hand
        if best_hand is None or hand_rank < best_hand:
            best_hand = hand_rank
            winner_id = player_id

    # Declare the winner
    game_data["players"][winner_id]["capital"]+=game_data["pot"]
    winner_name = game_data["players"][winner_id]["name"]
    txt = ""
    context.bot.send_message(chat_id, f"🏆 {winner_name} wins with {txt.join(game_data['players'][winner_id]['cards'])}! 🎉 \n\nTable: {txt.join(game_data['table'])}")
    context.bot.send_message(chat_id,"Start a new game by clicking /startgame")

def evaluate_hand(cards):
    """Converts a list of card strings into a rank using treys"""
    evaluator = Evaluator()

    # Convert cards into Treys format
    treys_cards = [Card.new(card) for card in cards]

    # Get hand rank (lower is better)
    rank = evaluator.evaluate(treys_cards[:2], treys_cards[2:])  # Two-hole cards & five community cards

    return rank  # Lower rank means stronger hand

def start_new_betting_round(context: CallbackContext, chat_id):
    """Starts a new betting round after Flop, Turn, or River by selecting the first active player (last raiser or small blind)."""
    global game_data

    player_ids = list(game_data["players"].keys())

    small_blind_index = game_data["small_blind_pos"] % len(player_ids)
    first_player_id = None

    for i in range(len(player_ids)):  # Loop through players to find an active one
        check_index = (small_blind_index + i) % len(player_ids)
        check_player = player_ids[check_index]
        if not game_data["players"][check_player]["folded"]:
            first_player_id = check_player
            break

    if not first_player_id:
        context.bot.send_message(chat_id, "⚠️ No active players left to start a betting round.")
        return

    # **Set the Current Player**
    game_data["current_player"] = first_player_id
    game_data["last_raise"] = 0
    game_data["last_to_raise"] = first_player_id  # Reset last raise tracking for this round

    # **Announce New Betting Round**
    context.bot.send_message(chat_id, f"💰 New betting round begins! {game_data['players'][first_player_id]['name']} acts first.")

    # **Send Turn Notification for the First Player**
    send_player_turn(context, chat_id)


def generate_deck():
    """Generates a new shuffled deck."""
    suits = {'♠': 's', '♥': 'h', '♣': 'c', '♦': 'd'}  # Convert suits to treys format
    ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    return [rank + suit for rank in ranks for suit in suits]

def capital(update: Update, context: CallbackContext):
    global game_data

    players_capital = "\n".join([f"{p_data['name']}: {p_data['capital']}" for p_data in game_data["players"].values()])
    capital_text = f"**Capital balance:**\n{players_capital}"

    context.bot.send_message(update.message.chat_id, capital_text)


def main() -> None:
    updater = Updater("INPUT TOKEN HERE", use_context=True)
    dispatcher = updater.dispatcher

    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("startgame", startgame))
    dispatcher.add_handler(CommandHandler("fold", fold))
    dispatcher.add_handler(CommandHandler("check", check))
    dispatcher.add_handler(CommandHandler("call", call))
    dispatcher.add_handler(CommandHandler("raise", raise_bet))
    dispatcher.add_handler(CommandHandler("capital", capital))
    dispatcher.add_handler(CallbackQueryHandler(button_tap))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()