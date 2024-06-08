import torch
import torch.nn as nn
import torch.optim as optim
from torchvision import datasets, models, transforms
from torch.utils.data import DataLoader, Dataset
import os
from PIL import Image
from dataloader import NCKUFinalDataset
from tqdm import tqdm
#from densenet_twolayer import *
import torch.nn.functional as F


import random
from torchvision.models import densenet121


class DynamicConv2d(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0):
        super(DynamicConv2d, self).__init__()
        self.in_channels = in_channels
        self.out_channels = out_channels
        self.kernel_size = kernel_size
        self.stride = stride
        self.padding = padding
        
        self.weight_generator = nn.Sequential(
            nn.Linear(in_channels, 128),
            nn.ReLU(),
            nn.Linear(128, out_channels * in_channels * kernel_size * kernel_size)
        )
        
    def forward(self, x):
        batch_size, in_channels, height, width = x.size()
        assert in_channels == self.in_channels
        
        # Generate weights dynamically for each input in the batch
        outputs = []
        for i in range(batch_size):
            input_tensor = x[i].view(in_channels, -1).mean(dim=1)
            weights = self.weight_generator(input_tensor)
            weights = weights.view(self.out_channels, self.in_channels, self.kernel_size, self.kernel_size)
            output = F.conv2d(x[i:i+1], weights, stride=self.stride, padding=self.padding)
            outputs.append(output)
        return torch.cat(outputs, dim=0)

class ModifiedDenseNet(nn.Module):
    def __init__(self, num_classes=50):
        super(ModifiedDenseNet, self).__init__()
        self.densenet = densenet121(pretrained=True)
        
        # Replace the first convolutional layer with DynamicConv2d
        self.densenet.features.conv0 = DynamicConv2d(in_channels=3, out_channels=64, kernel_size=7, stride=2, padding=3)
        
        # Modify the classifier to match the number of classes
        self.densenet.classifier = nn.Linear(1024, num_classes)
        
    def forward(self, x):
        return self.densenet(x)
        
        
class ChannelShuffle(object):
    def __init__(self, p=0.5):
        self.p = p

    def __call__(self, img):
        if isinstance(img, Image.Image):  # Check if img is a PIL Image
            img = transforms.ToTensor()(img)
        if random.random() < self.p:
            channels = list(img.unbind(0))
            random.shuffle(channels)
            img = torch.stack(channels, dim=0)
        return transforms.ToPILImage()(img)  # Convert back to PIL Image


# Update the data_transforms dictionary
data_transforms = {
    'train': transforms.Compose([
        transforms.RandomResizedCrop(224),
        transforms.RandomHorizontalFlip(),
        ChannelShuffle(p=0.5),  # Add the channel shuffle here
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
    'val': transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        ChannelShuffle(p=0.5),  # Add the channel shuffle here
        transforms.ToTensor(),
        transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    ]),
}

#model = DenseNet_TWOLAYER(num_classes=50)
#model = DynamicConv2d(in_channels=3, out_channels=64, kernel_size=3, stride=1, padding=1)


def adjust_lr(optimizer, num_epochs):
    if num_epochs in [100, 150, 180]:
        for p in optimizer.param_groups:
            p['lr'] *= 0.1
            lr = p['lr']
        print('Change lr:'+str(lr))
        
def random_channel_permutation(image):
    channels = [0, 1, 2]
    random.shuffle(channels)
    return image[channels, :, :]

def train_model(model, dataloaders, criterion, optimizer, num_epochs=200):
    best_model_wts = model.state_dict()
    best_acc = 0.0

    for epoch in range(num_epochs):
        print(f'Epoch {epoch}/{num_epochs - 1}')
        print('-' * 10)

        for phase in ['train', 'val']:
            if phase == 'train':
                model.train()
                adjust_lr(optimizer, epoch)
            else:
                model.eval()

            running_loss = 0.0
            running_corrects = 0

            dataloader = dataloaders[phase]
            progress_bar = tqdm(dataloader, desc=f"{phase} {epoch}/{num_epochs - 1}")

            for inputs, labels in progress_bar:
                inputs = inputs.cuda()
                labels = labels.cuda()

                optimizer.zero_grad()

                with torch.set_grad_enabled(phase == 'train'):
                    outputs = model(inputs)
                    _, preds = torch.max(outputs, 1)
                    loss = criterion(outputs, labels)

                    if phase == 'train':
                        loss.backward()
                        optimizer.step()

                running_loss += loss.item() * inputs.size(0)
                running_corrects += torch.sum(preds == labels.data)

                progress_bar.set_postfix(loss=loss.item(), acc=torch.sum(preds == labels.data).item() / len(labels))

            epoch_loss = running_loss / len(dataloader.dataset)
            epoch_acc = running_corrects.double() / len(dataloader.dataset)

            print(f'{phase} Loss: {epoch_loss:.4f} Acc: {epoch_acc:.4f}')

            if phase == 'val' and epoch_acc > best_acc:
                best_acc = epoch_acc
                best_model_wts = model.state_dict()
                torch.save(best_model_wts, 'checkpoint_dw_model.pth')

    print(f'Best val Acc: {best_acc:4f}')
    model.load_state_dict(best_model_wts)
    return model

def random_channel_permutation(image):
    channels = [0, 1, 2]
    random.shuffle(channels)
    return image[channels, :, :]


# Load datasets


dataset_train = NCKUFinalDataset(txt_file="/ssd4/ming/final/train.txt", transform=data_transforms['train'])
dataset_val = NCKUFinalDataset(txt_file="/ssd4/ming/final/val.txt", transform=data_transforms['val'])

dataloader_train = DataLoader(dataset_train, batch_size=32, shuffle=True, num_workers=8)
dataloader_val = DataLoader(dataset_val, batch_size=1, shuffle=False, num_workers=1)

dataloaders = {'train': dataloader_train, 'val': dataloader_val}



# Initialize model, loss function, and optimizer
model = ModifiedDenseNet(num_classes=50).cuda()
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

# Train the model
model = train_model(model, dataloaders, criterion, optimizer, num_epochs=200)

# Testing with random channel permutations
dataset_val = NCKUFinalDataset(txt_file="/ssd4/ming/final/test.txt", transform=data_transforms['val'])
test_loader = DataLoader(test_dataset, batch_size=1, shuffle=False)

model.eval()
correct = 0
total = 0
with torch.no_grad():
    for images, labels in test_loader:
        permuted_images = torch.stack([random_channel_permutation(img) for img in images])
        permuted_images = permuted_images.cuda()
        labels = labels.cuda()

        outputs = model(permuted_images)
        _, predicted = torch.max(outputs.data, 1)
        total += labels.size(0)
        correct += (predicted == labels).sum().item()

    print(f'Accuracy of the model with random channel permutations: {100 * correct / total:.2f}%')


torch.save(model.state_dict(), 'best_dw_model.pth')
