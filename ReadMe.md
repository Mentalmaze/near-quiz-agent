# Mental Maze Telegram Quiz Bot

A blockchain-powered quiz game bot for Telegram that leverages NEAR Protocol for reward distribution and uses AI to generate trivia questions.

## Overview

Mental Maze Bot enables engaging quiz competitions in Telegram groups where players can win NEAR tokens as rewards. Quiz creators can easily set up custom quizzes by simply specifying a topic, while our AI backend handles question generation. Winners receive their rewards directly to their linked NEAR wallets through a transparent and automated process.

## Features

### For Quiz Creators

- **Easy Quiz Creation**: Generate quiz questions about any topic using AI
- **Customizable Rewards**: Define prize structures (e.g., "2 NEAR for 1st place, 1 NEAR for 2nd place")
- **Automated Funding**: Secure deposit of quiz rewards through direct NEAR wallet integration
- **Transparent Results**: Public leaderboard showing winners and their rewards

### For Players

- **Secure Wallet Linking**: Connect NEAR wallets through a private verification process
- **Private Quiz Participation**: Answer questions through direct messages to prevent cheating
- **Interactive UI**: Respond to questions using inline keyboard buttons
- **Automatic Rewards**: Receive winnings directly to linked wallets

### Security Features

- Private messaging for sensitive operations
- Blockchain-based wallet verification
- Isolated question delivery to prevent cheating
- Secure database storage of user information and quiz data

## Technology Stack

### Core Components

- **Python**: Primary programming language
- **Telegram Bot API**: User interaction and command handling
- **SQLAlchemy ORM**: Database interactions and model definitions
- **SQLite**: Lightweight database for storing quiz and user data
- **NEAR Protocol**: Blockchain integration for wallet validation and reward distribution
- **LangChain + Google Gemini**: AI-powered quiz question generation

### Key Components

#### 1. Quiz Model

The quiz system tracks:

- Topic and questions
- Reward structure and deposit address
- Quiz status (DRAFT, FUNDING, ACTIVE, CLOSED)
- Group chat origin and participants

#### 2. User Management

- Secure wallet linking with challenge-response verification
- Quiz participation tracking
- Answer recording with timestamps for tiebreaker resolution

#### 3. Blockchain Integration

- Monitors NEAR blockchain for deposits to activate quizzes
- Verifies wallet ownership
- Automates reward distribution to winners

#### 4. Question Generation

Leverages Google's Gemini API through LangChain to create engaging multiple-choice questions on any topic.

## Command Structure

- `/createquiz <topic>` - Start a new quiz creation process
- `/linkwallet` - Link your NEAR wallet to participate in quizzes
- `/playquiz [quiz_id]` - Join an active quiz (latest quiz if no ID provided)
- `/winners [quiz_id]` - View current leaderboard or final results

## Error Handling

The bot implements comprehensive error handling with:

- Automatic retries for network timeouts
- Graceful failure modes for blockchain connectivity issues
- User-friendly error messages
- Detailed server-side logging

## Data Flow

1. **Quiz Creation**: Group chat → Topic selection → AI question generation → Reward structure (private chat) → NEAR deposit → Quiz activation
2. **Player Participation**: Wallet linking → Quiz registration → Private question delivery → Answer submission → Scoring → Reward distribution

## Transparency

All quiz results are publicly displayed in the group chat to ensure transparency in the reward distribution process. The `/winners` command allows anyone to view the current standings or final results of any quiz.
