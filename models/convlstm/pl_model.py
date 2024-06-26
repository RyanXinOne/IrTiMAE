import os
import torch
from torch import optim
import torch.nn.functional as F
import lightning.pytorch as pl
from models.convlstm import ConvLSTMForecaster
from data.utils import interpolate_sequence, visualise_sequence, calculate_ssim_series, calculate_psnr_series


class LitConvLSTM(pl.LightningModule):
    def __init__(self):
        super().__init__()
        self.model = ConvLSTMForecaster(input_dim=1, hidden_dim=1, kernel_size=3, num_layers=1)
        self.forecast_steps = 5
        self.visualise_num = 5

    def configure_optimizers(self):
        optimizer = optim.AdamW(self.parameters(), lr=1e-3, weight_decay=1e-2)
        return optimizer

    def training_step(self, batch, batch_idx):
        x, y, mask = batch

        x_int = x.clone()
        for i in range(len(x_int)):
            x_int[i] = interpolate_sequence(x_int[i], mask[i])

        x_pred, y_pred = self.model(x_int, y)
        loss = self.compute_loss(
            torch.cat([x, y], dim=1),
            torch.cat([x_pred, y_pred], dim=1),
        )
        self.log('train/mse', loss)
        return loss

    def validation_step(self, batch, batch_idx):
        x, y, mask = batch

        x_int = x.clone()
        for i in range(len(x_int)):
            x_int[i] = interpolate_sequence(x_int[i], mask[i])

        with torch.no_grad():
            x_pred, y_pred = self.model.predict(x_int, self.forecast_steps)
            loss = self.compute_loss(
                torch.cat([x, y], dim=1),
                torch.cat([x_pred, y_pred], dim=1),
            )
        self.log('val/mse', loss)
        return loss

    def test_step(self, batch, batch_idx):
        x, y, mask = batch
        data = torch.cat([x, y], dim=1)

        x_int = x.clone()
        for i in range(len(x_int)):
            x_int[i] = interpolate_sequence(x_int[i], mask[i])

        with torch.no_grad():
            x_pred, y_pred = self.model.predict(x_int, self.forecast_steps)
            pred = torch.cat([x_pred, y_pred], dim=1)
            loss = self.compute_loss(data, pred)
            ssim_value = calculate_ssim_series(data, pred)
            psnr_value = calculate_psnr_series(data, pred)
        self.log('test/mse', loss)
        self.log('test/ssim', ssim_value)
        self.log('test/psnr', psnr_value)
        return loss

    def predict_step(self, batch, batch_idx):
        x, y, mask = batch

        x_int = x.clone()
        for i in range(len(x_int)):
            x_int[i] = interpolate_sequence(x_int[i], mask[i])

        batch_size = len(x)
        os.makedirs('logs/convlstm/output', exist_ok=True)

        with torch.no_grad():
            x_pred, y_pred = self.model.predict(x_int, self.forecast_steps)

        for i in range(batch_size):
            vi = batch_idx * batch_size + i
            if vi >= self.visualise_num:
                break
            input_ = torch.cat([x[i], y[i]], dim=0)
            output = torch.cat([x_pred[i], y_pred[i]], dim=0)
            diff = torch.abs(input_ - output)
            visualise_sequence(input_, save_path=f'logs/convlstm/output/input_{vi}.png')
            visualise_sequence(output, save_path=f'logs/convlstm/output/predict_{vi}.png')
            visualise_sequence(diff, save_path=f'logs/convlstm/output/diff_{vi}.png')
        return y_pred

    def compute_loss(self, x, pred):
        return F.mse_loss(pred, x)
