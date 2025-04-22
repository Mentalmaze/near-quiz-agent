/**
 * # Mental Maze Telegram Quiz Bot Documentation
 *
 * ## Overview
 * A Telegram bot facilitating quiz games with NEAR blockchain integration for rewards distribution.
 *
 * ## Core Components
 *
 * ### Quiz Creator Module
 * - Handles quiz creation and setup
 * - Manages reward structure
 * - Integrates with NEAR blockchain for fund deposits
 *
 * ### Player Management Module
 * - Manages player registration
 * - Handles wallet linking
 * - Processes quiz participation
 *
 * ### Blockchain Integration Module
 * - Validates wallet connections
 * - Monitors fund deposits
 * - Executes reward distributions
 *
 * ## Key Features
 *
 * ### Security
 * - Private messaging for sensitive operations
 * - Wallet verification through signed messages
 * - Secure question delivery system
 *
 * ### Command Structure
 * - /createquiz: Initiates quiz creation
 * - /linkwallet: Connects NEAR wallet
 * - /playquiz: Joins active quiz
 *
 * ### Workflow
 * 1. Quiz Creation:
 *    - Topic specification
 *    - Reward structure setup
 *    - Fund deposit verification
 *
 * 2. Player Participation:
 *    - Wallet linking
 *    - Quiz registration
 *    - Question answering
 *    - Reward distribution
 *
 * ## Technical Requirements
 * - Telegram Bot API integration
 * - NEAR blockchain connectivity
 * - LangChain for question generation
 * - Secure message signing capability
 *
 * ## Implementation Notes
 * - 24-hour quiz duration unless when specified by the creator
 * - Automated scoring system
 * - Direct wallet-to-wallet transfers
 * - Private messaging for quiz answers
 *
 * @version 1.0
 * @author Mental Maze Team

## Game Creator’s Process

The game creator sets up the quiz by defining the topic, generating questions, and funding the rewards. Here’s how they’ll go about it:

### Step 1: Initiate Quiz Creation
- **Creator’s Action:**
  Types `/createquiz` in the Telegram group chat.
- **Bot’s Response:**
  _"@[CreatorUsername], let’s create a quiz! ."_ which is only visible to the creator and then an input for the topic of the quiz
- **Creator’s Action:**
 Replies and sends the quiz topic (e.g., "Science trivia").
- **Bot’s Response:**
  - Generates multiple-choice questions using a tool like LangChain based on the topic.
  - Replies: _"Quiz questions generated! Now, please specify the reward structure, e.g., '2 Near for 1st place, 1 Near for 2nd place'."_
- **Details:**
  - The bot creates a set of questions automatically.
  - It then prompts the creator to define the prize structure.

### Step 3: Define the Reward Structure
- **Creator’s Action:**
  Replies in the private chat with the reward details (e.g., "2 Near for 1st, 1 Near for 2nd").
- **Bot’s Response:**
  - Calculates the total reward amount (e.g., 3 Near).
  - Provides a Near wallet address: _"Please deposit 3 Near to this address: [wallet_address]."_
- **Details:**
  - The bot sums the rewards to determine the total deposit required.
  - It gives a unique wallet address for the creator to send funds.

### Step 4: Fund the Quiz
- **Creator’s Action:**
  Transfers the specified amount (e.g., 3 Near) to the provided wallet address using their Near wallet.
- **Bot’s Response:**
  - Monitors the blockchain for the deposit confirmation.
  - Once confirmed, announces in the group: _"New quiz created: Science Trivia! Rewards: 2 Near (1st), 1 Near (2nd). Type `/playquiz` to join. Ends in 24 hours."_
- **Details:**
  - The bot waits for blockchain confirmation to ensure funds are secure.
  - The quiz becomes active, and players can join.

---

## Game Player’s Process

The game player participates in the quiz, answers questions, and competes for rewards. Here’s their step-by-step process:

### Step 1: Link a Near Wallet (If Not Already Done)
- **Player’s Action:**
  Types `/linkwallet` in the group chat if they haven’t linked their wallet yet.
- **Bot’s Response:**
  _"@[PlayerUsername], please start a private chat with me to link your Near wallet securely."_
- **Private Linking Process:**
  1. **Player’s Action:** Starts a private chat and sends their Near wallet address.
  2. **Bot’s Response:** _"Please sign this message: '[random_string]' and send me the signature."_
  3. **Player’s Action:** Signs the message using their wallet and sends the signature back.
  4. **Bot’s Response:** _"Wallet linked! You’re ready to play."_
- **Details:**
  - Linking is a one-time setup to enable reward payouts.
  - The signed message verifies wallet ownership securely.

### Step 2: Join the Quiz
- **Player’s Action:**
  Types `/playquiz` in the group chat.
- **Bot’s Response:**
  - If the wallet is linked: _"@[PlayerUsername], you’re in! I’ll send you the first question privately."_
  - If not linked: _"Please link your wallet first with `/linkwallet`."_
- **Details:**
  - The bot checks for a linked wallet before allowing participation.
  - Players are registered and moved to private messaging for gameplay.

### Step 3: Answer Quiz Questions
- **Bot’s Action:**
  Sends the first question privately with an inline keyboard:
  _"Question 1: What is the chemical symbol for water?
  A) H2O  B) CO2  C) O2  D) N2"_
- **Player’s Action:**
  Selects an answer by tapping a button (e.g., A).
- **Bot’s Response:**
  - Sends the next question after each answer.
  - Repeats until all questions are answered, then confirms: _"Quiz submitted! Results will be announced in the group."_
- **Details:**
  - Questions are delivered via private messages to prevent cheating.
  - Inline keyboards ensure easy, trackable responses.

### Step 4: Receive Results and Rewards
- **Bot’s Action:**
  - After the quiz ends (e.g., after 24 hours), evaluates all submissions.
  - Determines winners based on correct answers and submission times.
  - Announces in the group: _"Quiz results! 1st: @[Winner1] (2 Near), 2nd: @[Winner2] (1 Near). Rewards sent to your wallets!"_
  - Automatically transfers Near tokens to the winners’ linked wallets.
- **Player’s Action:**
  - Checks their wallet to confirm receipt of rewards (no action required if they don’t win).
- **Details:**
  - The bot handles scoring and payout distribution.
  - Results are public, but rewards go directly to wallets.

---

## Key Points for Coding

- **Commands:**
  - `/createquiz` (group): Starts quiz creation.
  - `/linkwallet` (group): Initiates wallet linking.
  - `/playquiz` (group): Registers players.
- **Private Interactions:**
  - Creator: Topic and reward setup.
  - Player: Wallet linking and question answering.
- **Security:**
  - Wallet linking uses signed messages for verification.
  - Questions are answered privately via inline keyboards.
- **Blockchain Integration:**
  - Monitor deposits for quiz activation.
  - Automate reward transfers to winners.
- **Timing:**
  - Set a quiz duration (e.g., 24 hours) and evaluate results at the end.
