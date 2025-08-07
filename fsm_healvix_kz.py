from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message
from aiogram.filters import Command

router = Router()

class HealvixFSM(StatesGroup):
    greet = State()
    problem = State()
    warning = State()
    solution = State()
    offer = State()
    objections = State()
    order = State()

@router.message(Command("start"))
async def start_fsm(message: Message, state: FSMContext):
    await message.answer("Сәлеметсіз бе! Менің атым — Айдос, мен Healvix компаниясының маманымын.\n"
                         "Сіз көзге арналған табиғи кешен бойынша өтінім қалдырған едіңіз — 1-2 минут сөйлесуге уақытыңыз бар ма?")
    await state.set_state(HealvixFSM.problem)

@router.message(HealvixFSM.problem)
async def get_problem(message: Message, state: FSMContext):
    await state.update_data(problem=message.text)
    await message.answer("Өтінімді өзіңіз үшін қалдырдыңыз ба, әлде жақындарыңызға ма?\n"
                         "Қандай белгілер мазалайды — көздің шаршауы, бұлыңғыр көру, көру қабілетінің төмендеуі?")
    await state.set_state(HealvixFSM.warning)

@router.message(HealvixFSM.warning)
async def give_warning(message: Message, state: FSMContext):
    await state.update_data(symptoms=message.text)
    await message.answer("Иә, қазіргі заманда мұндай жағдай өте жиі кездеседі. Экран, стресс, жас ерекшеліктері — бұлардың бәрі көзге ауырлық түсіреді.\n\n"
                         "Өкінішке қарай, көп адам алғашқы белгілерге мән бермейді. Бірақ уақыт өте келе жағдай ушығады — көз құрғауы, көрудің нашарлауы, көзілдірікке дейін.\n"
                         "Ал көз — ол бұлшық емес, бір кеткен соң қайтару қиын.")
    await message.answer("Көру қабілетін жоғалту — жай ғана ыңғайсыздық емес. Бұл — жақындарыңызды анық көре алмау.\n"
                         "Сіз дәл қазір дұрыс қадам жасадыңыз — мәселе ушығып кетпей тұрып алдын алу ең тиімді шешім.")
    await state.set_state(HealvixFSM.solution)

@router.message(HealvixFSM.solution)
async def give_solution(message: Message, state: FSMContext):
    await message.answer("Healvix — бұл көзді табиғи жолмен қорғайтын және қалпына келтіретін кешен.\n"
                         "Құрамында: мия (черника), лютеин, В дәрумендері бар.\n"
                         "Бұл компоненттер:\n"
                         "🔹 көздің ішкі тіндерін қоректендіреді\n"
                         "🔹 шаршауды басады\n"
                         "🔹 көрудің нашарлауын баяулатады.")
    await message.answer("Клиенттердің айтуынша, 2 апта ішінде көру қабілетінің жақсарғаны байқалады.")
    await state.set_state(HealvixFSM.offer)

@router.message(HealvixFSM.offer)
async def make_offer(message: Message, state: FSMContext):
    await message.answer("Қазір сіздің өтініміңіз бойынша арнайы жеңілдік бар.\n"
                         "Жеткізу — тегін. Төлем — тек алған кезде.\n"
                         "Қалайсыз: бір айлық курс па, әлде толық нәтиже үшін 2–3 айға аласыз ба?")
    await state.set_state(HealvixFSM.objections)

@router.message(HealvixFSM.objections)
async def handle_objections(message: Message, state: FSMContext):
    text = message.text.lower()

    if "ойлану" in text:
        await message.answer("Әрине, түсінемін. Бірақ көру — кейінге қалдыруға болмайтын нәрсе.\n"
                             "Қазір бір қаптамамен бастап, көз жеткізуге мүмкіндік бар. Тәуекел жоқ.")
    elif "жаман емес" in text or "онша емес" in text:
        await message.answer("Дәл осындай кезең — алдын алуға таптырмас уақыт.\n"
                             "Көру нашарлаған кезде қалпына келтіру әлдеқайда қиын әрі қымбат.")
    elif "сенбеймін" in text or "көмектеспейді" in text:
        await message.answer("Біз ғажайыпқа уәде бермейміз. Бірақ клиенттердің 80%-дан астамы оң әсер байқаған.")
    else:
        await message.answer("Түсіндім. Бірақ көру — ең құнды дүниелердің бірі. Өз көзіңізге қамқор болыңыз.")

    await message.answer("Онда келістік, тапсырысты рәсімдейік.\n"
                         "Жеткізу курьермен немесе пошта арқылы болады. Төлем — алған кезде.\n"
                         "Тек толық аты-жөніңізді, мекенжай мен нөміріңізді жазсаңыз болды.")
    await state.set_state(HealvixFSM.order)

@router.message(HealvixFSM.order)
async def confirm_order(message: Message, state: FSMContext):
    await message.answer("Тапсырыс қабылданды! Жақын күндері сізбен байланысамыз.\n"
                         "Көру қабілетіңізге бүгіннен бастап қамқорлық жасағаныңыз — өте дұрыс шешім!\n"
                         "Күніңіз сәтті өтсін!")
    await state.clear()
