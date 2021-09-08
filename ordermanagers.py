from threading import Thread
from time import sleep
import math

from binance import ThreadedWebsocketManager, Client

import loggercrypto


WARNING_NOT_CLOSED_ORDER="NOT_CLOSED_ORDER"
WARNING_UNEXPECTED_WS="UNEXPECTED_WS"


class Spot:

    def __init__(self, api_key, api_secret, enableTestnet, symbol):
        self.api_key = api_key
        self.api_secret = api_secret
        self.enableTestnet=enableTestnet
        self.connector = Client(api_key=api_key, api_secret=api_secret, testnet=enableTestnet)

        self.symbol = symbol

        info = self.connector.get_symbol_info(symbol=symbol)
        self.baseAsset = info["baseAsset"] # Название базового актива.
        self.quoteAsset = info["quoteAsset"] # Название котировочного актива. В нем идет торговля!
        self.round_price = abs(round(math.log(float(info['filters'][0]['tickSize']), 10)))  # округление цены
        self.round_qty = abs(round(math.log(float(info['filters'][2]['stepSize']), 10))) # округление количества
        self.minNotional = float(info['filters'][3]['minNotional']) # минимальное значение price*qty
        # self.quotePrecision = info['quotePrecision'] # котировочная точность, нигде не используется

        self.baseAsset_balance = 0.0
        self.quoteAsset_balance = 0.0
        self.bnb_balance = 0.0
        self._update_balance()

        self.orderId = 0
        self.orderStatus = "BOT_INIT"
        self.orderSide = "BOT_INIT"
        self.orderPrice = 0.0
        self.orderQuantity = 0.0
        self.orderFilledQuantity = 0.0
        self.ordersZombie = []

        self.logger = loggercrypto.get_logger("orderManager")
        self._logging_info()


    def sell(self, price, quantity):
        response = self.connector.order_limit_sell(symbol=self.symbol,
                                                  price=round(price, self.round_price),
                                                  quantity=round(quantity, self.round_qty),
                                                  # newClientOrderId=f"{time}",
                                                  newOrderRespType="RESULT" # "FULL"
                                                  )
        if self.orderStatus in ["NEW", "PARTIALLY_FILLED"]:
            self.ordersZombie.append(self.orderId)
            self._logging_warning(comment=WARNING_NOT_CLOSED_ORDER)

        self.orderId = response["orderId"]
        self.orderStatus = response["status"]
        self.orderSide = response["side"]
        self.orderPrice = float(response["price"])
        self.orderQuantity = float(response["origQty"])
        self.orderFilledQuantity = float(response["executedQty"])

    def sell_stopLoss(self, price, quantity):
        raise NotImplemented

    def buy(self, price, quantity):
        response = self.connector.order_limit_buy(symbol=self.symbol,
                                                  price=round(price, self.round_price),
                                                  quantity=round(quantity, self.round_qty),
                                                  # newClientOrderId=f"{time}",
                                                  newOrderRespType="RESULT" #"FULL"
                                                  )

        if self.orderStatus in ["NEW", "PARTIALLY_FILLED"]:
            self.ordersZombie.append(self.orderId)
            self._logging_warning(comment=WARNING_NOT_CLOSED_ORDER)

        self.orderId = response["orderId"]
        self.orderStatus = response["status"]
        self.orderSide = response["side"]
        self.orderPrice = float(response["price"])
        self.orderQuantity = float(response["origQty"])
        self.orderFilledQuantity = float(response["executedQty"])

    def buy_stopLoss(self, price, quantity):
        raise NotImplemented

    def cancel(self):
        response = self.connector.cancel_order(symbol=self.symbol, orderId=self.orderId)
        self.orderStatus = response["status"]
        self.orderFilledQuantity = float(response["executedQty"])

    def cancel_zombies(self):
        for orderId in self.ordersZombie:
            response_status = self.connector.get_order(symbol=self.symbol, orderId=orderId, recvWindow=60000)
            if response_status["status"] in ["NEW", "PARTIALLY_FILLED"]:
                response = self.connector.cancel_order(symbol=self.symbol, orderId=orderId)
                self._logging_info_response(response=response)
        self.ordersZombie = []


    def transposition_sellBuy(self):
        tmp = self.buy
        self.buy = self.sell
        self.sell = tmp

    # def use_testnet(self):
    #     self.connector = Client(api_key=self.api_key, api_secret=self.api_secret, testnet=True)

    def start_ws(self):
        self.ws_userdatastreams = ThreadedWebsocketManager(api_key=self.api_key, api_secret=self.api_secret)
        self.ws_userdatastreams.start()
        self.ws_userdatastreams.start_user_socket(callback=self._callback_userdatastreams)

    def stop_ws(self):
        self.ws_userdatastreams.stop()
        self.ws_userdatastreams.join()

    def start_pollStatusManually(self):
        self.pollStatus_continue = True
        self.th_pollStatus = Thread(target=self._pollStatus, args=[])
        self.th_pollStatus.start()

    def stop_pollStatusManually(self):
        self.pollStatus_continue = False
        self.th_pollStatus.join()

    def _callback_userdatastreams(self, msg):
        eventType = msg["e"]
        if (eventType == "executionReport"):
            if (msg["i"] == self.orderId):
                #transactionTime = msg["T"]
                #executionType = msg["x"]
                self.orderStatus = msg["X"]
                self.orderFilledQuantity = float(msg["z"])
                self._logging_info()

        elif eventType == "outboundAccountPosition":
            # Информация о балансе аккаунта: все монеты и free\locked
            # Возможно он будет просираться на каждую монету и инстанс и засрет весь лог балансом
            for asset_info in msg["B"]:
                if asset_info["a"] == self.baseAsset:
                    self.baseAsset_balance = float(asset_info["f"])
                elif asset_info["a"] == self.quoteAsset:
                    self.quoteAsset_balance = float(asset_info["f"])
                elif asset_info["a"] == "BNB":
                    self.bnb_balance = float(asset_info["f"])
            self._logging_info_balance()

        elif eventType == "balanceUpdate":
            # обновление баланса
            return

        elif eventType == "listStatus":
            # Сообщение об исполнении, если ордер является OCO
            return

        else:
            self._logging_warning(comment=WARNING_UNEXPECTED_WS)
            # такого быть не может
            return

    def _pollStatus(self, timeout=0.1):
        raise NotImplemented
        # orderId_prev = self.orderId
        # orderStatus_prev = self.orderStatus
        # while(self.pollStatus_continue):
        #     if self.orderStatus == "BOT_INIT":
        #         sleep(timeout)
        #         continue
        #     # if self.orderStatus in ["BOT_INIT", "FILLED", "CANCELED","PENDING_CANCEL","REJECTED","EXPIRED"]:
        #     #     orderId_prev = self.orderId
        #     #     sleep(timeout)
        #     #     continue
        #     response = self.connector.get_order(symbol=self.symbol, orderId=self.orderId, recvWindow=60000)
        #     executedQty = float(response["executedQty"])
        #     if (self.orderId != orderId_prev) or\
        #             (self.orderStatus != orderStatus_prev) or\
        #             (self.orderFilledQuantity != executedQty):
        #         self._update_balance()
        #         self.orderStatus = response["status"]
        #         self.orderFilledQuantity = executedQty
        #         self._logging_info()
        #     orderId_prev = self.orderId
        #     orderStatus_prev = self.orderStatus
        #     sleep(timeout)

    def _update_balance(self):
        self.baseAsset_balance = float(self.connector.get_asset_balance(self.baseAsset)['free'])
        self.quoteAsset_balance = float(self.connector.get_asset_balance(self.quoteAsset)['free'])
        self.bnb_balance = float(self.connector.get_asset_balance("BNB")['free'])

    def _logging_info(self):
        self.logger.info(
            f"{self.orderSide}-{self.orderId} {self.orderStatus} price={self.orderPrice} "
            f"{self.orderFilledQuantity}/{self.orderQuantity} "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")

    def _logging_info_response(self, response):
        orderId = response["orderId"]
        orderStatus = response["status"]
        orderSide = response["side"]
        orderPrice = float(response["price"])
        orderQuantity = float(response["origQty"])
        orderFilledQuantity = float(response["executedQty"])
        self.logger.info(
            f"{orderSide}-{orderId} {orderStatus} price={orderPrice} "
            f"{orderFilledQuantity}/{orderQuantity} "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")

    def _logging_info_balance(self):
        self.logger.info(
            f"UPDATE BALANCE: "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")

    def _logging_warning(self, comment):
        self.logger.warning(
            f"{comment} {self.orderSide}-{self.orderId} {self.orderStatus} price={self.orderPrice} "
            f"{self.orderFilledQuantity}/{self.orderQuantity} "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")



