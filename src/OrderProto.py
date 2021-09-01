from binance import ThreadedWebsocketManager, Client
from threading import Thread
from time import sleep
import math

import logging

class orderProto():

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
        # self.minNotional = float(info['filters'][3]['minNotional']) # минимальное значение price*qty
        # self.quotePrecision = info['quotePrecision'] # котировочная точность, нигде не используется

        self.baseAsset_balance = 0.0
        self.quoteAsset_balance = 0.0
        self.bnb_balance = 0.0
        self._update_balance()

        self.orderId = 0
        self.orderStatus = "EMPTY"
        self.orderQuantity = 0.0
        self.orderFilledQuantity = 0.0
        self.ordersZombie = []

        #_log_format = "[%(asctime)s] %(levelname)-8s - %(name) - (%(filename)s).%(funcName)s(%(lineno)d) - %(message)s"
        _log_format = "[%(asctime)s] %(levelname)-8s %(message)s"
        logging.basicConfig(filename="log", format=_log_format, level=logging.INFO, datefmt="%H:%M:%S %d-%m-%Y")
        logging.info(
            f"INIT-{self.orderId} {self.orderStatus} price={0.0} {self.orderFilledQuantity}/{self.orderQuantity} "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")

    def sell(self, price, quantity):
        response = self.connector.order_limit_sell(symbol=self.symbol,
                                                  price=round(price,self.round_price),
                                                  # newClientOrderId="BUY_"+self.orderSide+"_"+str(self.timeNow),
                                                  timeInForce='GTC',
                                                  quantity=round(quantity,self.round_qty))
        if self.orderStatus in ["NEW", "PARTIALLY_FILLED"]:
            self.ordersZombie.append(self.orderId)
            logging.warning(
                f"NOTCLOSED-{self.orderId} {self.orderStatus} price=- {self.orderFilledQuantity}/{self.orderQuantity} "
                f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
                f"BNB={self.bnb_balance}")

        self._update_balance()

        self.orderId = response["orderId"]
        side = response["side"]
        self.orderStatus = response["status"]
        self.orderQuantity = float(response["origQty"])
        self.orderFilledQuantity = float(response["executedQty"])
        logging.info(
            f"{side}-{self.orderId} {self.orderStatus} price={price} {self.orderFilledQuantity}/{self.orderQuantity} "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")

    def sell_stopLoss(self, price, quantity):
        raise NotImplemented

    def buy(self, price, quantity):
        response = self.connector.order_limit_buy(symbol=self.symbol,
                                           price=round(price,self.round_price),
                                           # newClientOrderId="BUY_"+self.orderSide+"_"+str(self.timeNow),
                                           timeInForce='GTC',
                                           quantity=round(quantity,self.round_qty))
        if self.orderStatus in ["NEW", "PARTIALLY_FILLED"]:
            self.ordersZombie.append(self.orderId)
            logging.warning(
                f"NOTCLOSED-{self.orderId} {self.orderStatus} price=- {self.orderFilledQuantity}/{self.orderQuantity} "
                f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
                f"BNB={self.bnb_balance}")

        self._update_balance()

        self.orderId = response["orderId"]
        side = response["side"]
        self.orderStatus = response["status"]
        self.orderQuantity = quantity
        self.orderFilledQuantity = float(response["executedQty"])
        logging.info(
            f"{side}-{self.orderId} {self.orderStatus} price={price} {self.orderFilledQuantity}/{self.orderQuantity} "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")

    def buy_stopLoss(self, price, quantity):
        raise NotImplemented

    def cancel(self):
        response = self.connector.cancel_order(symbol=self.symbol, orderId=self.orderId)
        self._update_balance()

        side = response["side"]
        price = response["price"]
        self.orderStatus = response["status"]
        self.orderFilledQuantity = float(response["executedQty"])
        logging.info(
            f"{side}-{self.orderId} {self.orderStatus} price={price} {self.orderFilledQuantity}/{self.orderQuantity} "
            f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
            f"BNB={self.bnb_balance}")

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
        if eventType == "executionReport":
            # проблема кучи ловушек и кучи монет
            # проверка соответствия id
            if (msg["i"] != self.orderId):
                return
            # Сообщение об исполнении https://binance-docs.github.io/apidocs/spot/en/#payload-order-update
            orderId = msg["i"]
            #transactionTime = msg["T"]
            # могут быть статусы:
            # NEW\TRADE(FILLED или PARTIALLY_FILLED)\CANCELED\REPLACED(не использ.)\REJECTED\EXPIRED
            #executionType = msg["x"]
            self.orderStatus = msg["X"]
            # сколько заполнено
            self.orderFilledQuantity = float(msg["z"])
            #смен полей класса!

        elif eventType == "outboundAccountPosition":
            # Информация о балансе аккаунта: все монеты и free\locked
            for asset_info in msg["B"]:
                if asset_info["a"] == self.baseAsset:
                    self.baseAsset_balance = float(asset_info["f"])
                elif asset_info["a"] == self.quoteAsset:
                    self.quoteAsset_balance = float(asset_info["f"])
                elif asset_info["a"] == "BNB":
                    self.bnb_balance = float(asset_info["f"])


        elif eventType == "balanceUpdate":
            # обновление баланса
            return

        elif eventType == "listStatus":
            # Сообщение об исполнении, если ордер является OCO
            return

        else:
            # такого быть не может
            return

    def _pollStatus(self, timeout=0.1):
        while(self.pollStatus_continue):
            if self.orderStatus in ["EMPTY", "FILLED", "CANCELED","PENDING_CANCEL","REJECTED","EXPIRED"]:
                sleep(timeout)
                continue
            response = self.connector.get_order(symbol=self.symbol, orderId=self.orderId, recvWindow=60000)
            executedQty = float(response["executedQty"])
            if self.orderFilledQuantity != executedQty:
                self._update_balance()

                side = response["side"]
                price = response["price"]
                self.orderStatus = response["status"]
                self.orderFilledQuantity = executedQty
                logging.info(
                    f"{side}-{self.orderId} {self.orderStatus} price={price} {self.orderFilledQuantity}/{self.orderQuantity} "
                    f"{self.baseAsset}={self.baseAsset_balance} {self.quoteAsset}={self.quoteAsset_balance} "
                    f"BNB={self.bnb_balance}")
            sleep(timeout)

    def _update_balance(self):
        self.baseAsset_balance = float(self.connector.get_asset_balance(self.baseAsset)['free'])
        self.quoteAsset_balance = float(self.connector.get_asset_balance(self.quoteAsset)['free'])
        self.bnb_balance = float(self.connector.get_asset_balance("BNB")['free'])

