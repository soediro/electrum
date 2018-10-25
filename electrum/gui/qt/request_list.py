#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import QTreeWidgetItem, QMenu, QHeaderView

from electrum.i18n import _
from electrum.util import format_time, age
from electrum.plugin import run_hook
from electrum.paymentrequest import PR_UNKNOWN
from electrum.bitcoin import COIN

from .util import MyTreeWidget, pr_tooltips, pr_icons


REQUEST_TYPE_BITCOIN = 0
REQUEST_TYPE_LN = 1


class RequestList(MyTreeWidget):
    filter_columns = [0, 1, 2, 3]  # Date, Address, Description, Amount

    def __init__(self, parent):
        MyTreeWidget.__init__(self, parent, self.create_menu, [_('Date'), _('Address'), _('Description'), _('Amount'), _('Status')], 2)
        self.currentItemChanged.connect(self.item_changed)
        self.itemClicked.connect(self.item_changed)
        self.setSortingEnabled(True)
        self.setColumnWidth(0, 180)
        self.setColumnWidth(1, 250)

    def update_headers(self, headers):
        self.setColumnCount(len(headers))
        self.setHeaderLabels(headers)
        self.header().setStretchLastSection(False)
        for col in range(len(headers)):
            if col in [1]: continue
            sm = QHeaderView.Stretch if col == self.stretch_column else QHeaderView.ResizeToContents
            self.header().setSectionResizeMode(col, sm)

    def item_changed(self, item):
        if item is None:
            return
        if not item.isSelected():
            return
        request_type = item.data(0, Qt.UserRole)
        key = str(item.data(1, Qt.UserRole))
        if request_type == REQUEST_TYPE_BITCOIN:
            req = self.parent.get_request_URI(key)
        elif request_type == REQUEST_TYPE_LN:
            preimage, req = self.wallet.lnworker.invoices.get(key)
        self.parent.receive_address_e.setText(req)

    def on_update(self):
        self.wallet = self.parent.wallet
        # hide receive tab if no receive requests available
        b = len(self.wallet.receive_requests) > 0 or len(self.wallet.lnworker.invoices) > 0
        self.setVisible(b)
        self.parent.receive_requests_label.setVisible(b)
        if not b:
            self.parent.expires_label.hide()
            self.parent.expires_combo.show()
            return

        domain = self.wallet.get_receiving_addresses()
        # clear the list and fill it again
        self.clear()
        for req in self.wallet.get_sorted_requests(self.config):
            address = req['address']
            if address not in domain:
                continue
            timestamp = req.get('time', 0)
            amount = req.get('amount')
            expiration = req.get('exp', None)
            message = req.get('memo', '')
            date = format_time(timestamp)
            status = req.get('status')
            signature = req.get('sig')
            requestor = req.get('name', '')
            amount_str = self.parent.format_amount(amount) if amount else ""
            URI = self.parent.get_request_URI(address)
            item = QTreeWidgetItem([date, address, message, amount_str, pr_tooltips.get(status,'')])
            if signature is not None:
                item.setIcon(1, self.icon_cache.get(":icons/seal.png"))
                item.setToolTip(1, 'signed by '+ requestor)
            if status is not PR_UNKNOWN:
                item.setIcon(6, self.icon_cache.get(pr_icons.get(status)))
            item.setData(0, Qt.UserRole, REQUEST_TYPE_BITCOIN)
            item.setData(1, Qt.UserRole, address)
            self.addTopLevelItem(item)
        # lightning
        for payreq_key, (preimage_hex, invoice) in self.wallet.lnworker.invoices.items():
            from electrum.lnaddr import lndecode
            import electrum.constants as constants
            lnaddr = lndecode(invoice, expected_hrp=constants.net.SEGWIT_HRP)
            amount_sat = lnaddr.amount*COIN if lnaddr.amount else None
            amount_str = self.parent.format_amount(amount_sat) if amount_sat else ''
            description = ''
            for k,v in lnaddr.tags:
                if k == 'd':
                    description = v
                    break
            date = format_time(lnaddr.date)
            item = QTreeWidgetItem([date, invoice, description, amount_str, ''])
            item.setIcon(1, self.icon_cache.get(":icons/lightning.png"))
            item.setData(0, Qt.UserRole, REQUEST_TYPE_LN)
            item.setData(1, Qt.UserRole, payreq_key)  # RHASH hex
            self.addTopLevelItem(item)

    def create_menu(self, position):
        item = self.itemAt(position)
        if not item:
            return
        request_type = item.data(0, Qt.UserRole)
        menu = None
        if request_type == REQUEST_TYPE_BITCOIN:
            menu = self.create_menu_bitcoin_payreq(item)
        elif request_type == REQUEST_TYPE_LN:
            menu = self.create_menu_ln_payreq(item)
        if menu:
            menu.exec_(self.viewport().mapToGlobal(position))

    def create_menu_bitcoin_payreq(self, item):
        addr = str(item.data(1, Qt.UserRole))
        req = self.wallet.receive_requests.get(addr)
        if req is None:
            self.update()
            return
        column = self.currentColumn()
        column_title = self.headerItem().text(column)
        column_data = item.text(column)
        menu = QMenu(self)
        uri = self.parent.get_request_URI(addr)
        menu.addAction(_("Copy"), lambda: self.parent.app.clipboard().setText(uri))
        menu.addAction(_("Copy {}").format(column_title), lambda: self.parent.app.clipboard().setText(column_data))
        menu.addAction(_("Save as BIP70 file"), lambda: self.parent.export_payment_request(addr))
        menu.addAction(_("Delete"), lambda: self.parent.delete_payment_request(addr))
        run_hook('receive_list_menu', menu, addr)
        return menu

    def create_menu_ln_payreq(self, item):
        payreq_key = item.data(1, Qt.UserRole)
        preimage, req = self.wallet.lnworker.invoices.get(payreq_key)
        if req is None:
            self.update()
            return
        column = self.currentColumn()
        column_title = self.headerItem().text(column)
        column_data = item.text(column)
        menu = QMenu(self)
        menu.addAction(_("Copy"), lambda: self.parent.app.clipboard().setText(req))
        menu.addAction(_("Copy {}").format(column_title), lambda: self.parent.app.clipboard().setText(column_data))
        menu.addAction(_("Delete"), lambda: self.parent.delete_lightning_payreq(payreq_key))
        return menu
