import math
from time import time

from binance import ThreadedWebsocketManager

import loggercrypto

ERROR_NOT_CORRECT_PARAMS = "NOT_CORRECT_PARAMS"


class Trap:
    def __init__(self, orderManager, walletPercent, position, burstPercent, recoveryPercent,
                 partiallyFilled_timer,
                 buffer_percentLower, buffer_percentUpper, buffer_timer,
                 stopLoss_timerActivate,
                 stopLoss_percentActivate,
                 stopLoss_percentStart, stopLoss_percentStep, stopLoss_percentFinish,
                 stopLoss_timerStep):
        """
        Криптобот, работающий по алгоритму "Ловушка"
        Внимание: все проценты считаются от цены входа в алгоритм
        :param orderManager: Объект orderManager
        :param walletPercent: Сколько процентов баланса кошелька используется ботом.
        :param position: SHORT или LONG
        :param burstPercent: на сколько процентов от price ловим скачек
        :param recoveryPercent: на сколько проц. от price цена восстановится после скачка (recoveryPercent<burstPercent)
        :param buffer_percentLower: на сколько процентов от price верхняя граница буфера
        :param buffer_percentUpper:
        :param buffer_timer:
        :param stopLoss_percentStart:
        :param stopLoss_percentStep:
        :param stopLoss_percentFinish:
        :param stopLoss_timerStart:
        :param stopLoss_timerStep:
        """
        self.orderManager = orderManager
        self.walletPercent = walletPercent
        self.walletMultiplier = self.walletPercent / 100.0
        self.position = position  # SHORT\LONG

        self.partiallyFilled_timer = partiallyFilled_timer

        assert recoveryPercent < burstPercent, ERROR_NOT_CORRECT_PARAMS
        self.burstPercent = burstPercent
        self.recoveryPercent = recoveryPercent
        if self.position == "SHORT":
            self.burstMultiplier = 1.0 + self.burstPercent / 100.0
            self.recoveryMultiplier = 1.0 + self.recoveryPercent / 100.0
        elif self.position == "LONG":
            self.burstMultiplier = 1.0 - self.burstPercent / 100.0
            self.recoveryMultiplier = 1.0 - self.recoveryPercent / 100.0

        self.buffer_percentLower = buffer_percentLower
        self.buffer_multiplierLower = 1.0 - self.buffer_percentLower / 100.0
        self.buffer_percentUpper = buffer_percentUpper
        self.buffer_multiplierUpper = 1.0 + self.buffer_percentUpper / 100.0
        self.buffer_timer = buffer_timer

        self.stopLoss_timerActivate = stopLoss_timerActivate
        self.stopLoss_percentActivate = stopLoss_percentActivate
        self.stopLoss_percentStart = stopLoss_percentStart
        self.stopLoss_percentStep = stopLoss_percentStep
        self.stopLoss_percentFinish = stopLoss_percentFinish
        n_multipliers = math.ceil(abs(
            (self.stopLoss_percentFinish - self.stopLoss_percentStart) / self.stopLoss_percentStep
        ))
        if self.position == "SHORT":
            self.stopLoss_multiplierActivate = 1.0 + self.stopLoss_percentActivate / 100.0
            self.stopLoss_multipliers = [1.0 + (self.stopLoss_percentStart + i * self.stopLoss_percentStep) / 100.0
                                         for i in range(n_multipliers)]
            self.stopLoss_multipliers.append(1.0 + self.stopLoss_percentFinish / 100.0)
        elif self.position == "LONG":
            self.stopLoss_multiplierActivate = 1.0 - self.stopLoss_percentActivate / 100.0
            self.stopLoss_multipliers = [1.0 - (self.stopLoss_percentStart + i * self.stopLoss_percentStep) / 100.0
                                         for i in range(n_multipliers)]
            self.stopLoss_multipliers.append(1.0 - self.stopLoss_percentFinish / 100.0)

        self.stopLoss_idx = 0
        self.stopLoss_n = len(self.stopLoss_multipliers)
        self.stopLoss_timerStep = stopLoss_timerStep

        # состояние алгоритма
        self.stage = "STAGE1"
        self.priceEntry = 0.0
        self.quantity = 0.0
        self.timeEvent = 0.0
        self.buffer_priceLower = 0.0
        self.buffer_priceUpper = 0.0
        self.burstPrice = 0.0
        self.recoveryPrice = 0.0
        self.stopLoss_priceActivate = 0.0
        self.stopLoss_price = 0.0


        self.logger = loggercrypto.get_logger(__class__.__name__)


    def step(self, price, tradeTime):
        if self.position == "SHORT":
            self._step_short(price, tradeTime)
        elif self.position == "LONG":
            self._step_long(price, tradeTime)

    def _step_short(self, price, tradeTime):
        if self.stage == "STAGE1":
            self.priceEntry = price
            self.burstPrice = price * self.burstMultiplier
            self.quantity = self.orderManager.baseAsset_balance * self.walletMultiplier
            self.orderManager.sell(self.burstPrice, self.quantity)
            self.buffer_priceLower = price * self.buffer_multiplierLower
            self.buffer_priceUpper = price * self.buffer_multiplierUpper
            self.recoveryPrice = price * self.recoveryMultiplier
            self.stage = "STAGE2"
            return

        elif self.stage == "STAGE2":
            if self.orderManager.orderStatus == "FILLED":
                self.orderManager.buy(self.recoveryPrice, self.quantity)
                self.stage = "STAGE3"
                return
            elif self.orderManager.orderStatus == "PARTIALLY_FILLED":
                self.timeEvent = time()
                self.stage = "STAGE2a"
                return
            elif price > self.buffer_priceUpper:
                self.orderManager.cancel()
                self.stage = "STAGE1"
                return
            elif price < self.buffer_priceLower:
                self.timeEvent = time()
                self.stage = "STAGE2b"
                return

        elif self.stage == "STAGE2a":
            # PARTIALLY_FILLED ждем пока доделается или отменяем по таймеру
            if self.orderManager.orderStatus == "FILLED":
                self.orderManager.buy(self.recoveryPrice, self.quantity)
                self.stage = "STAGE3"
                return
            elif (time() - self.timeEvent) > self.partiallyFilled_timer:
                self.orderManager.cancel()
                self.quantity = self.orderManager.orderFilledQuantity
                self.orderManager.buy(self.recoveryPrice, self.quantity)
                self.stage = "STAGE3"
                return

        elif self.stage == "STAGE2b":
            # таймер буфера
            if price >= self.buffer_priceLower:
                self.stage = "STAGE2"
                return
            elif (time() - self.timeEvent) > self.buffer_timer:
                self.orderManager.cancel()
                self.stage = "STAGE1"
                return

        elif self.stage == "STAGE3":
            if self.orderManager.orderStatus == "FILLED":
                self.stage = "STAGE1"
                return
            else:
                self.timeEvent = time()
                self.stage = "STAGE4"
                return

        elif self.stage == "STAGE4":
            # ждем таймера stoploss
            if self.orderManager.orderStatus == "FILLED":
                self.stage = "STAGE1"
                return
            elif (time() - self.timeEvent) > self.stopLoss_timerActivate:
                self.stopLoss_priceActivate = price * self.stopLoss_multiplierActivate
                self.stage = "STAGE5"
                return

        elif self.stage == "STAGE5":
            if self.orderManager.orderStatus == "FILLED":
                self.stage = "STAGE1"
                return
            elif price >= self.stopLoss_priceActivate:
                # активация Stoploss
                self.orderManager.cancel()
                quantity_old = self.quantity
                self.quantity = self.orderManager.orderFilledQuantity
                self.stopLoss_price = price*self.stopLoss_multipliers[self.stopLoss_idx]
                self.stopLoss_idx+=1
                self.orderManager.buy(self.stopLoss_price, self.quantity)
                self.timeEvent = time()
                self.stage = "STAGE6"
                return
        elif self.stage == "STAGE6":
            #
            if self.orderManager.orderStatus == "FILLED":
                self.logger.info(f"{self.stage}-FINISH-STOP_LOSS price={price}")
                self.stage = "STAGE1"
                return
            elif (self.stopLoss_idx!=self.stopLoss_n) and ((time() - self.timeEvent) > self.stopLoss_timerStep):
                self.orderManager.cancel()
                quantity_old = self.quantity
                self.quantity = self.orderManager.orderFilledQuantity
                self.stopLoss_price = price * self.stopLoss_multipliers[self.stopLoss_idx]
                self.stopLoss_idx += 1
                self.orderManager.buy(self.stopLoss_price, self.quantity)
                self.timeEvent = time()
                return


    def _step_long(self, price, tradeTime):
        if self.stage == "STAGE1":
            self.priceEntry = price
            self.burstPrice = price * self.burstMultiplier
            self.quantity = self.orderManager.quoteAsset_balance * self.walletMultiplier / price
            self.orderManager.buy(self.burstPrice, self.quantity)
            self.buffer_priceLower = price * self.buffer_multiplierLower
            self.buffer_priceUpper = price * self.buffer_multiplierUpper
            self.recoveryPrice = price * self.recoveryMultiplier
            self.logger.info(f"{self.stage} price={price} Trap={self.burstPrice}/{self.recoveryPrice} "
                             f"[{self.buffer_priceLower}:{self.buffer_priceUpper}]")
            self.stage = "STAGE2"
            return

        elif self.stage == "STAGE2":
            if self.orderManager.orderStatus == "FILLED":
                self.orderManager.sell(self.recoveryPrice, self.quantity)
                self.logger.info(f"{self.stage}-FILLED price={price} Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE3"
                return
            elif self.orderManager.orderStatus == "PARTIALLY_FILLED":
                self.timeEvent = time()
                self.logger.info(f"{self.stage}-PARTIALLY_FILLED price={price} Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE2a"
                return
            elif price < self.buffer_priceLower:
                self.orderManager.cancel()
                self.logger.info(f"{self.stage}-BUFFER_LOWER price={price}")
                self.stage = "STAGE1"
                return
            elif price > self.buffer_priceUpper:
                self.timeEvent = time()
                self.logger.info(f"{self.stage}-BUFFER_UPPER price={price} Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE2b"
                return

        elif self.stage == "STAGE2a":
            # PARTIALLY_FILLED ждем пока доделается или отменяем по таймеру
            if self.orderManager.orderStatus == "FILLED":
                self.orderManager.sell(self.recoveryPrice, self.quantity)
                self.logger.info(f"{self.stage}-FILLED price={price} Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE3"
                return
            elif (time() - self.timeEvent) > self.partiallyFilled_timer:
                self.orderManager.cancel()
                quantity_old = self.quantity
                self.quantity = self.orderManager.orderFilledQuantity
                self.orderManager.sell(self.recoveryPrice, self.quantity)
                self.logger.info(f"{self.stage}-PARTIALLY_FILLED price={price} {quantity_old}/{self.quantity}"
                                 f" Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE3"
                return

        elif self.stage == "STAGE2b":
            # таймер буфера
            if price <= self.buffer_priceUpper:
                self.logger.info(f"{self.stage}-BUFFER_UPPER-PRICE_RECOVER price={price} "
                                 f"Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE2"
                return
            elif (time() - self.timeEvent) > self.buffer_timer:
                self.orderManager.cancel()
                self.logger.info(f"{self.stage}-BUFFER_UPPER-OUT_OF_TIME={(time() - self.timeEvent)} price={price}")
                self.stage = "STAGE1"
                return
        # Обработка Stop Loss'ов
        elif self.stage == "STAGE3":
            if self.orderManager.orderStatus == "FILLED":
                self.logger.info(f"{self.stage}-FINISH price={price}")
                self.stage = "STAGE1"
                return
            else:
                self.timeEvent = time()
                self.logger.info(f"{self.stage}-ACTIVATE-STOP_LOSS_TIMER"
                                 f"price={price} Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE4"
                return

        elif self.stage == "STAGE4":
            # ждем таймера stoploss
            if self.orderManager.orderStatus == "FILLED":
                self.logger.info(f"{self.stage}-FINISH price={price}")
                self.stage = "STAGE1"
                return
            elif (time() - self.timeEvent) > self.stopLoss_timerActivate:
                self.stopLoss_priceActivate = price * self.stopLoss_multiplierActivate
                self.logger.info(f"{self.stage}-ACTIVATE-STOP_LOSS_PRICE_ACTIVATE price={price} "
                                 f"priceActivate={self.stopLoss_priceActivate}  Trap={self.burstPrice}/{self.recoveryPrice}")
                self.stage = "STAGE5"
                return

        elif self.stage == "STAGE5":
            if self.orderManager.orderStatus == "FILLED":
                self.logger.info(f"{self.stage}-FINISH price={price}")
                self.stage = "STAGE1"
                return
            elif price <= self.stopLoss_priceActivate:
                # активация Stoploss
                self.orderManager.cancel()
                quantity_old = self.quantity
                self.quantity = self.orderManager.orderFilledQuantity
                self.stopLoss_price = price*self.stopLoss_multipliers[self.stopLoss_idx]
                self.stopLoss_idx+=1
                self.orderManager.sell(self.stopLoss_price, self.quantity)
                self.timeEvent = time()
                self.logger.info(f"{self.stage}-ACTIVATE_STOP_LOSS price={price} stopLoss={self.stopLoss_price}")
                self.stage = "STAGE6"
                return

        elif self.stage == "STAGE6":
            #
            if self.orderManager.orderStatus == "FILLED":
                self.logger.info(f"{self.stage}-FINISH-STOP_LOSS price={price} losses=Unknown")
                self.stage = "STAGE1"
                return
            elif (self.stopLoss_idx!=self.stopLoss_n) and ((time() - self.timeEvent) > self.stopLoss_timerStep):
                self.orderManager.cancel()
                quantity_old = self.quantity
                self.quantity = self.orderManager.orderFilledQuantity
                self.stopLoss_price = price * self.stopLoss_multipliers[self.stopLoss_idx]
                self.stopLoss_idx += 1
                self.orderManager.sell(self.stopLoss_price, self.quantity)
                self.timeEvent = time()
                self.logger.info(f"{self.stage}-STOP_LOSS price={price} stopLoss={self.stopLoss_price}")
                return








    def start_ws(self):
        api_key = self.orderManager.api_key
        api_secret = self.orderManager.api_secret
        symbol = self.orderManager.symbol
        self.ws_aggtrade = ThreadedWebsocketManager(api_key=api_key, api_secret=api_secret)
        self.ws_aggtrade.start()
        if self.position == "SHORT":
            self.ws_aggtrade.start_aggtrade_socket(callback=self._callback_aggtrade_short, symbol=symbol)
        elif self.position == "LONG":
            self.ws_aggtrade.start_aggtrade_socket(callback=self._callback_aggtrade_long, symbol=symbol)

    def stop_ws(self):
        self.ws_aggtrade.stop()
        self.ws_aggtrade.join()

    def _callback_aggtrade_short(self, msg):
        price = float(msg['p'])
        tradeTime = msg['T']
        self._step_short(price, tradeTime)

    def _callback_aggtrade_long(self, msg):
        price = float(msg['p'])
        tradeTime = msg['T']
        self._step_long(price, tradeTime)
