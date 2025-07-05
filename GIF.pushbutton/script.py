# -*- coding: utf-8 -*-
import os, inspect, clr
import math
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System')

# Global flag for outputting logs to print (debug window)
DEBUG_PRINT = False

from System.Collections.Generic import List
from System.IO import Directory
from System.Windows import Window, Visibility, GridLength
from System.Windows.Threading import DispatcherPriority
from System import Action
from System.Threading import Thread, ThreadStart

from pyrevit.framework import wpf
from pyrevit import revit, DB, forms

import System
from System.Drawing import Image, Imaging
from System.Drawing.Imaging import EncoderValue

SCRIPT_DIR = os.path.dirname(inspect.getfile(inspect.currentframe()))
XAML_PATH  = os.path.join(SCRIPT_DIR, 'ui.xaml')

MAX_PIXEL_SIZE = 15000  # Revit API hard limit: 1..15000 px per side (see Autodesk forums)

# --------------------- helpers ---------------------
class ParamSetting:
    def __init__(self, name, param_obj, min_val=0, max_val=100):
        self.Name = name
        self.ParamObj = param_obj
        self.MinValue = str(min_val)
        self.MaxValue = str(max_val)

def get_all_family_instances():
    return list(DB.FilteredElementCollector(revit.doc).OfClass(DB.FamilyInstance))

def get_numeric_params(elem):
    return [p for p in elem.Parameters
            if p.StorageType == DB.StorageType.Double and not p.IsReadOnly]

def export_frame(doc, view, folder, idx, resolution_dpi=600, pixel_size=2048, scale_factor=1.0):
    opts = DB.ImageExportOptions()
    opts.ExportRange = DB.ExportRange.VisibleRegionOfCurrentView
    opts.FilePath = os.path.join(folder, 'frame_{:03d}.png'.format(idx))
    
    # 1️⃣ Correct enum-DPI mapping
    dpi_enum = {
        72  : DB.ImageResolution.DPI_72,
        150 : DB.ImageResolution.DPI_150,
        300 : DB.ImageResolution.DPI_300,
        600 : DB.ImageResolution.DPI_600,
    }.get(resolution_dpi, DB.ImageResolution.DPI_600)  # ≥600 → DPI_600
    opts.ImageResolution = dpi_enum
    
    # 2️⃣ Apply scale factor to pixel size
    scaled_pixel_size = int(pixel_size * scale_factor)
    
    # 3️⃣ Clamp to Revit's hard limit
    if resolution_dpi > 600:
        final_pixel_size = int(scaled_pixel_size * (resolution_dpi / 600.0))
    else:
        final_pixel_size = scaled_pixel_size
    
    if final_pixel_size > MAX_PIXEL_SIZE:
        print("WARNING: Requested pixel size {} exceeds Revit's limit {}. Clamping.".format(final_pixel_size, MAX_PIXEL_SIZE))
        final_pixel_size = MAX_PIXEL_SIZE
    
    opts.PixelSize = final_pixel_size
    opts.FitDirection = DB.FitDirectionType.Horizontal
    opts.ShadowViewsFileType = DB.ImageFileType.PNG
    doc.ExportImage(opts)

def _safe(txt, fn):
    try: return fn(txt)
    except: return None

# ----------------------- UI ------------------------
class ParamUI(Window):
    def __init__(self):
        wpf.LoadComponent(self, XAML_PATH)
        self.instances = get_all_family_instances()
        self.familyBox.ItemsSource = [
            "{} #{}".format(i.Symbol.Family.Name, i.Id) for i in self.instances
        ]
        self.param_settings = []  # List of parameter settings
        self.paramSettingsList.ItemsSource = self.param_settings
        
        # Console setup
        self.console_visible = False
        self.show_logs = True
        self.show_console = False
        
        # Bind events to checkboxes
        self.showLogsBox.Checked += self.OnShowLogsChanged
        self.showLogsBox.Unchecked += self.OnShowLogsChanged
        
        # Bind events for scale settings
        self.scaleComboBox.SelectionChanged += self.OnScaleChanged
        self.customScaleBox.TextChanged += self.OnCustomScaleChanged
        self.dpiComboBox.SelectionChanged += self.OnExportSettingsChanged
        self.pixelSizeComboBox.SelectionChanged += self.OnExportSettingsChanged
        
        # Bind events for frames/duration/fps
        self.manualFramesRadio.Checked += self.OnFramesModeChanged
        self.durationFpsRadio.Checked += self.OnFramesModeChanged
        self.OnFramesModeChanged(None, None)
        
        # Bind events for GIF creation
        self.createGifCheckBox.Checked += self.OnCreateGifCheckChanged
        self.createGifCheckBox.Unchecked += self.OnCreateGifCheckChanged
        
        # Initial scale limiting
        self.limit_scale_options()

    def get_max_scale(self):
        dpi_values = [72, 150, 300, 600, 1200]
        pixel_size_values = [1024, 2048, 4096, 8192]
        dpi_index = self.dpiComboBox.SelectedIndex
        pixel_size_index = self.pixelSizeComboBox.SelectedIndex
        if dpi_index < 0:
            dpi_index = 2
        if pixel_size_index < 0:
            pixel_size_index = 1
        dpi = dpi_values[dpi_index]
        pixel_size = pixel_size_values[pixel_size_index]
        dpi_factor = max(1.0, float(dpi) / 600.0)
        max_scale = float(MAX_PIXEL_SIZE) / (pixel_size * dpi_factor)
        return max_scale

    def limit_scale_options(self):
        scale_values = [0.25, 0.5, 1.0, 1.5, 2.0, 4.0]
        max_scale = self.get_max_scale()
        # Remove all items and re-add only allowed ones
        self.scaleComboBox.Items.Clear()
        allowed_scales = []
        for scale in scale_values:
            if scale <= max_scale:
                allowed_scales.append(scale)
                self.scaleComboBox.Items.Add("{:.2f}x ({}%)".format(scale, int(scale*100)))
        # If nothing allowed, add at least 0.25x
        if not allowed_scales:
            allowed_scales = [0.25]
            self.scaleComboBox.Items.Add("0.25x (25%)")
        # Set selected index to max allowed or closest
        self.scaleComboBox.SelectedIndex = len(allowed_scales)-1
        # Also clamp custom scale if needed
        try:
            custom_scale = float(self.customScaleBox.Text)
        except:
            custom_scale = 1.0
        if custom_scale > max_scale:
            self.customScaleBox.Text = str(round(max_scale, 2))
            self.log("Custom scale was too high and has been clamped to {:.2f} (Revit max: {} px)".format(max_scale, MAX_PIXEL_SIZE))

    def OnExportSettingsChanged(self, sender, args):
        self.limit_scale_options()
        self.log("Scale options updated based on export settings.")

    def OnScaleChanged(self, sender, args):
        # When user selects a scale, update custom scale box
        try:
            scale_str = self.scaleComboBox.SelectedItem
            if scale_str:
                scale_val = float(scale_str.split('x')[0])
                self.customScaleBox.Text = str(scale_val)
                self.log('Scale changed to: {}'.format(scale_val))
        except Exception as e:
            self.log('Error parsing scale: {}'.format(e))

    def OnCustomScaleChanged(self, sender, args):
        # Clamp custom scale if needed
        max_scale = self.get_max_scale()
        try:
            custom_scale = float(self.customScaleBox.Text)
            if custom_scale > max_scale:
                self.customScaleBox.Text = str(round(max_scale, 2))
                self.log("Custom scale was too high and has been clamped to {:.2f} (Revit max: {} px)".format(max_scale, MAX_PIXEL_SIZE))
            elif custom_scale <= 0:
                self.customScaleBox.Text = "0.25"
                self.log("Custom scale must be positive. Set to minimum 0.25.")
        except ValueError:
            # Ignore invalid input while typing
            pass

    def log(self, message):
        """Adds a message to the log"""
        if DEBUG_PRINT:
            print(message)
        # Write only if console is visible
        if self.show_console and self.console_visible:
            def update_console():
                self.consoleBox.AppendText(message + "\n")
                self.consoleBox.ScrollToEnd()
                # Force through Dispatcher with delay
                def delayed_scroll():
                    self.consoleBox.ScrollToEnd()
                self.Dispatcher.BeginInvoke(DispatcherPriority.Background, Action(delayed_scroll))
            self.Dispatcher.Invoke(Action(update_console), DispatcherPriority.Background)

    def OnShowLogsChanged(self, sender, args):
        """Show/hide console by checkbox"""
        self.show_console = bool(getattr(self.showLogsBox, 'IsChecked', False))
        if self.show_console:
            self.consoleBorder.Visibility = Visibility.Visible
            self.consoleRow.Height = GridLength(150)
            self.console_visible = True
        else:
            self.consoleBorder.Visibility = Visibility.Collapsed
            self.consoleRow.Height = GridLength(0)
            self.console_visible = False

    def OnClearConsole(self, *_):
        """Clears the console and is immediately ready for new logs"""
        def clear_console():
            self.consoleBox.Text = ""
        self.Dispatcher.Invoke(Action(clear_console), DispatcherPriority.Background)

    def OnFamilyChanged(self, *_):
        if self.familyBox.SelectedIndex < 0: return
        self.update_params()

    def OnInstanceToggle(self, *_):
        self.update_params()

    def update_params(self):
        idx = self.familyBox.SelectedIndex
        if idx < 0: return
        inst = self.instances[idx]
        if self.instanceBox.IsChecked:
            self.par_objs = get_numeric_params(inst)
        else:
            self.par_objs = get_numeric_params(inst.Symbol)
        
        # Update parameter dropdown list
        param_names = [p.Definition.Name for p in self.par_objs]
        self.paramComboBox.ItemsSource = param_names
        if param_names:
            self.paramComboBox.SelectedIndex = 0

    def OnAddParameter(self, *_):
        """Adds the selected parameter to the settings list"""
        if self.paramComboBox.SelectedIndex < 0:
            self.log('Please select a parameter to add')
            return
        
        param_name = self.paramComboBox.SelectedItem
        param_obj = self.par_objs[self.paramComboBox.SelectedIndex]
        
        # Check if this parameter is already added
        for setting in self.param_settings:
            if setting.Name == param_name:
                self.log('Parameter "{}" is already added'.format(param_name))
                return
        
        # Add new parameter
        param_setting = ParamSetting(
            name=param_name,
            param_obj=param_obj,
            min_val=0,
            max_val=100
        )
        self.param_settings.append(param_setting)
        self.paramSettingsList.ItemsSource = None
        self.paramSettingsList.ItemsSource = self.param_settings
        self.log('Parameter added: {}'.format(param_name))

    def OnRemoveParameter(self, sender, *_):
        """Removes parameter from settings list"""
        param_setting = sender.Tag
        if param_setting in self.param_settings:
            self.param_settings.remove(param_setting)
            self.paramSettingsList.ItemsSource = None
            self.paramSettingsList.ItemsSource = self.param_settings
            self.log('Parameter removed: {}'.format(param_setting.Name))

    def OnBrowse(self, *_):
        try:
            from System.Windows.Forms import FolderBrowserDialog, DialogResult
            dlg = FolderBrowserDialog()
            dlg.Description = "Select a folder to save files"
            
            if dlg.ShowDialog() == DialogResult.OK:
                path = dlg.SelectedPath
                self.log('Dialog returned path: {}'.format(path))
                
                # Small delay for dialog completion
                import time
                time.sleep(0.1)
                
                # Try direct update method
                self.folderBox.Text = path
                self.log('Direct update, current value: {}'.format(self.folderBox.Text))
                
                # If direct method doesn't work, use dispatcher
                if self.folderBox.Text != path:
                    self.log('Direct update failed, using dispatcher')
                    def update_text():
                        self.log('Updating text field via dispatcher to: {}'.format(path))
                        self.folderBox.Text = path
                        # Force display update
                        self.folderBox.UpdateLayout()
                        self.log('Text field updated via dispatcher, current value: {}'.format(self.folderBox.Text))
                    
                    # Use dispatcher for UI update
                    self.Dispatcher.Invoke(Action(update_text), DispatcherPriority.Normal)
                
                self.log('Folder selected: {}'.format(path))
        except Exception as e:
            self.log('Error selecting folder: {}'.format(e))
            forms.alert(u'Error selecting folder: {}'.format(e))

    def OnCancel(self, *_):
        self.Close()

    def OnProceed(self, *_):
        try:
            if not self.console_visible:
                self.consoleBorder.Visibility = Visibility.Visible
                self.consoleRow.Height = GridLength(150)
                self.console_visible = True
            self.show_console = True
            self.progressBar.Value = 0
            self.progressBar.Visibility = Visibility.Visible
            self.log('Proceed clicked')
            self.log('Starting checks...')
            self.log('Checking family selection: SelectedIndex = {}'.format(self.familyBox.SelectedIndex))
            if self.familyBox.SelectedIndex < 0:
                self.log('Error: No family selected')
                return
            self.log('Family selected ✓')
            self.log('Checking parameter selection...')
            if not self.param_settings:
                self.log('Error: No parameters selected')
                return
            self.log('Parameters selected ✓')
            self.log('Parsing values from fields...')
            # --- FRAMES LOGIC ---
            if bool(getattr(self.durationFpsRadio, 'IsChecked', False)):
                duration = _safe(self.durationBox.Text, float)
                fps = _safe(self.fpsBox.Text, float)
                if duration is None or duration <= 0 or fps is None or fps <= 0:
                    self.log('Invalid duration or FPS')
                    return
                frames = int(math.ceil(duration * fps))
                self.log('Calculated frames: {} ({} sec × {} fps)'.format(frames, duration, fps))
            else:
                frames = _safe(self.framesBox.Text, int)
                if frames is None or frames < 2:
                    self.log('Invalid number of frames')
                    return
            folder = self.folderBox.Text
            self.log('folderBox.Text = "{}"'.format(folder))
            self.log('Checking value correctness...')
            if frames is None or frames < 2:
                self.log('Error: Invalid number of frames')
                return
            self.log('Number of frames is correct ✓')
            if not folder or not folder.strip():
                self.log('Error: No output folder selected')
                return
            self.log('Folder specified ✓')
            if not Directory.Exists(folder):
                self.log('Error: Folder not found: {}'.format(folder))
                return
            self.log('Folder exists ✓')
            self.log('Checking parameter settings...')
            for param_setting in self.param_settings:
                min_val = _safe(param_setting.MinValue, float)
                max_val = _safe(param_setting.MaxValue, float)
                if min_val is None or max_val is None or min_val == max_val:
                    self.log('Error: Invalid values for parameter {}'.format(param_setting.Name))
                    return
            self.log('Parameter settings are correct ✓')
            self.log('All checks passed, starting animation...')
            self.sel_inst = self.instances[self.familyBox.SelectedIndex]
            self.is_instance = bool(getattr(self.instanceBox, 'IsChecked', False))
            self.sel_param_settings = self.param_settings
            self.frames, self.folder = frames, folder
            dpi_values = [72, 150, 300, 600, 1200]
            pixel_size_values = [1024, 2048, 4096, 8192]
            dpi_index = self.dpiComboBox.SelectedIndex
            pixel_size_index = self.pixelSizeComboBox.SelectedIndex
            if dpi_index < 0:
                dpi_index = 2  # по умолчанию 300
            if pixel_size_index < 0:
                pixel_size_index = 1  # по умолчанию 2048
            self.resolution_dpi = dpi_values[dpi_index]
            self.pixel_size = pixel_size_values[pixel_size_index]
            self.log('Выбрано: DPI = {}, Pixel size = {}'.format(self.resolution_dpi, self.pixel_size))
            self.scale_factor = float(self.customScaleBox.Text) if self.customScaleBox.Text else 1.0
            self.log('Data saved: instance={}, params={}, frames={}, folder={}, dpi={}, pixel_size={}, scale={}'.format(
                self.sel_inst.Id, len(self.sel_param_settings), self.frames, self.folder, self.resolution_dpi, self.pixel_size, self.scale_factor))
            run_animation(self)
        except Exception as e:
            self.log('CRITICAL ERROR in OnProceed: {}'.format(e))
            import traceback
            self.log('Traceback:')
            self.log(traceback.format_exc())
        finally:
            self.progressBar.Visibility = Visibility.Collapsed

    def OnFramesModeChanged(self, sender, args):
        if bool(getattr(self.manualFramesRadio, 'IsChecked', False)):
            self.framesBox.IsEnabled = True
            self.durationBox.IsEnabled = False
            self.fpsBox.IsEnabled = False
            self.log("Manual frames mode enabled.")
        else:
            self.framesBox.IsEnabled = False
            self.durationBox.IsEnabled = True
            self.fpsBox.IsEnabled = True
            self.log("Duration/FPS mode enabled.")

    def OnCreateGifCheckChanged(self, sender, args):
        # Enable/disable loop checkbox based on createGifCheckBox
        try:
            create_gif_checked = bool(getattr(self.createGifCheckBox, 'IsChecked', False))
            self.log('Create GIF checkbox changed to: {}'.format(create_gif_checked))
            
            if create_gif_checked:
                self.loopGifCheckBox.IsEnabled = True
                self.log('Loop checkbox enabled')
            else:
                self.loopGifCheckBox.IsEnabled = False
                self.loopGifCheckBox.IsChecked = False
                self.log('Loop checkbox disabled and unchecked')
        except Exception as e:
            self.log('Error in OnCreateGifCheckChanged: {}'.format(e))

    def create_gif_from_frames(self, folder, out_gif, loop_inf=True):
        import System
        from System.Drawing import Image, Imaging
        from System.Drawing.Imaging import EncoderValue
        import os
        
        self.log('Starting GIF creation with loop_inf={}'.format(loop_inf))
        
        files = sorted([f for f in os.listdir(folder) if f.lower().endswith('.png')])
        if not files:
            self.log("No PNG frames found in folder.")
            return
        
        self.log('Found {} PNG files'.format(len(files)))
        
        try:
            images = [Image.FromFile(os.path.join(folder, f)) for f in files]
            w, h = images[0].Width, images[0].Height
            self.log('First image size: {}x{}'.format(w, h))
            
            for img in images:
                if img.Width != w or img.Height != h:
                    self.log('All frames must have the same size!')
                    for im in images:
                        im.Dispose()
                    return
            
            encoder = Imaging.Encoder.SaveFlag
            enc = Imaging.EncoderParameters(1)
            
            # Find GIF codec
            gif_codec = None
            for c in Imaging.ImageCodecInfo.GetImageEncoders():
                try:
                    if c.FormatID.Equals(Imaging.ImageFormat.Gif.Guid):
                        gif_codec = c
                        break
                except Exception as e:
                    self.log('Error comparing codec GUID: {}'.format(e))
                    continue
            
            if gif_codec is None:
                self.log('GIF codec not found!')
                for im in images:
                    im.Dispose()
                return
            
            self.log('GIF codec found: {}'.format(gif_codec.CodecName))
            
            # --- Netscape loop extension ---
            if loop_inf:
                self.log('Creating GIF with infinite loop...')
                
                def patch_gif_loop(gif_path):
                    try:
                        # Read file content
                        with open(gif_path, 'rb') as f:
                            content = bytearray(f.read())
                        
                        header = b'\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00'
                        
                        # Check if header already exists
                        header_exists = False
                        for i in range(len(content) - len(header) + 1):
                            if content[i:i+len(header)] == header:
                                header_exists = True
                                break
                        
                        if not header_exists:
                            # Find position to insert header (after GIF header and color table)
                            pos = 13
                            if len(content) > 10 and (content[10] & 0x80) != 0:
                                gct_size = 3 * (2 ** ((content[10] & 0x07) + 1))
                                pos += gct_size
                            
                            # Insert header at position
                            new_content = content[:pos] + header + content[pos:]
                            
                            # Write back to file
                            with open(gif_path, 'wb') as f:
                                f.write(new_content)
                            
                            self.log('GIF loop extension added successfully at position {}'.format(pos))
                        else:
                            self.log('GIF loop extension already exists')
                            
                    except Exception as e:
                        self.log('Error adding loop extension: {}'.format(e))
                        import traceback
                        self.log('Loop extension traceback: {}'.format(traceback.format_exc()))
                

                
                # Alternative method: Try to create GIF with loop using different approach
                try:
                    # Method 1: Standard .NET approach
                    enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.MultiFrame))
                    images[0].Save(out_gif, gif_codec, enc)
                    
                    enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.FrameDimensionTime))
                    for i, img in enumerate(images[1:], 1):
                        img2 = img.Clone()
                        images[0].SaveAdd(img2, enc)
                        img2.Dispose()
                        if i % 10 == 0:
                            self.log('Added frame {} to GIF'.format(i))
                    
                    enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.Flush))
                    images[0].SaveAdd(enc)
                    images[0].Dispose()
                    
                    for img in images[1:]:
                        img.Dispose()
                    
                    # Try to add loop extension
                    patch_gif_loop(out_gif)
                    self.log('GIF created with infinite loop: {}'.format(out_gif))
                    
                except Exception as e:
                    self.log('Error with standard GIF creation: {}'.format(e))
                    # Fallback: Create without loop extension
                    self.log('Falling back to GIF without loop extension...')
                    
                    # Clean up any existing images
                    try:
                        for img in images:
                            img.Dispose()
                    except:
                        pass
                    
                    # Recreate images
                    images = [Image.FromFile(os.path.join(folder, f)) for f in files]
                    
                    enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.MultiFrame))
                    images[0].Save(out_gif, gif_codec, enc)
                    
                    enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.FrameDimensionTime))
                    for i, img in enumerate(images[1:], 1):
                        img2 = img.Clone()
                        images[0].SaveAdd(img2, enc)
                        img2.Dispose()
                        if i % 10 == 0:
                            self.log('Added frame {} to GIF (fallback)'.format(i))
                    
                    enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.Flush))
                    images[0].SaveAdd(enc)
                    images[0].Dispose()
                    
                    for img in images[1:]:
                        img.Dispose()
                    
                    self.log('GIF created without loop extension (fallback): {}'.format(out_gif))
            else:
                self.log('Creating GIF without loop...')
                
                enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.MultiFrame))
                images[0].Save(out_gif, gif_codec, enc)
                
                enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.FrameDimensionTime))
                for i, img in enumerate(images[1:], 1):
                    img2 = img.Clone()
                    images[0].SaveAdd(img2, enc)
                    img2.Dispose()
                    if i % 10 == 0:
                        self.log('Added frame {} to GIF'.format(i))
                
                enc.Param[0] = Imaging.EncoderParameter(encoder, int(EncoderValue.Flush))
                images[0].SaveAdd(enc)
                images[0].Dispose()
                
                for img in images[1:]:
                    img.Dispose()
                
                self.log('GIF created (no loop extension): {}'.format(out_gif))
                
        except Exception as e:
            self.log('Error in create_gif_from_frames: {}'.format(e))
            import traceback
            self.log('Traceback: {}'.format(traceback.format_exc()))
            # Clean up images if they exist
            try:
                for img in images:
                    img.Dispose()
            except:
                pass

    def OnCreateGif(self, sender, args):
        try:
            self.log('OnCreateGif called')
            folder = self.folderBox.Text
            self.log('Folder from UI: "{}"'.format(folder))
            
            if not folder or not folder.strip():
                self.log('Output folder is not set.')
                return
                
            if not os.path.isdir(folder):
                self.log('Output folder does not exist: {}'.format(folder))
                return
                
            out_gif = os.path.join(folder, 'animation.gif')
            self.log('Output GIF path: {}'.format(out_gif))
            
            loop_inf = False
            if hasattr(self, 'loopGifCheckBox') and self.loopGifCheckBox is not None:
                try:
                    loop_inf = bool(getattr(self.loopGifCheckBox, 'IsChecked', False))
                    self.log('Loop checkbox state: {}'.format(loop_inf))
                except Exception as e:
                    self.log('Error reading loop checkbox: {}'.format(e))
                    loop_inf = False
            else:
                self.log('Loop checkbox not found')
            
            self.log('Calling create_gif_from_frames with loop_inf={}'.format(loop_inf))
            self.create_gif_from_frames(folder, out_gif, loop_inf=loop_inf)
            
        except Exception as e:
            self.log('Error creating GIF: {}'.format(e))
            import traceback
            self.log('Traceback: {}'.format(traceback.format_exc()))

# --------------------- main ------------------------
def run_animation(ui):
    try:
        ui.progressBar.Visibility = Visibility.Visible
        ui.progressBar.Minimum = 0
        ui.progressBar.Maximum = ui.frames
        ui.progressBar.Value = 0
        ui.log('Dialog confirmed, starting animation...')
        doc, view = revit.doc, revit.doc.ActiveView
        ui.log('Animation parameters: frames={}, params={}, dpi={}, pixel_size={}, scale={}'.format(
            ui.frames, len(ui.sel_param_settings), ui.resolution_dpi, ui.pixel_size, ui.scale_factor))
        for i in range(ui.frames):
            ui.log('Processing frame {}/{}'.format(i+1, ui.frames))
            with revit.Transaction('Animate params'):
                if ui.is_instance:
                    elem = doc.GetElement(ui.sel_inst.Id)
                else:
                    elem = doc.GetElement(ui.sel_inst.Symbol.Id)
                for param_setting in ui.sel_param_settings:
                    min_val = float(param_setting.MinValue)
                    max_val = float(param_setting.MaxValue)
                    step = (max_val - min_val) / float(ui.frames - 1)
                    val = min_val + i * step
                    ui.log('Setting parameter {} to value: {}'.format(param_setting.Name, val))
                    pp = elem.LookupParameter(param_setting.Name)
                    if pp:
                        try:
                            pp.Set(DB.UnitUtils.ConvertToInternalUnits(val, pp.GetUnitTypeId()))
                            ui.log('Parameter {} set to {} (new API)'.format(param_setting.Name, val))
                        except:
                            try:
                                pp.Set(DB.UnitUtils.ConvertToInternalUnits(val, pp.DisplayUnitType))
                                ui.log('Parameter {} set to {} (old API)'.format(param_setting.Name, val))
                            except Exception as e:
                                pp.Set(val)
                                ui.log('Parameter {} set to {} (direct)'.format(param_setting.Name, val))
            try:
                doc.RefreshActiveView()
                ui.log('View refreshed')
            except:
                ui.log('Skipping view refresh')
            # Calculate final pixel size for logging
            scaled_pixel_size = int(ui.pixel_size * ui.scale_factor)
            if ui.resolution_dpi > 600:
                final_pixel_size = int(scaled_pixel_size * (ui.resolution_dpi / 600.0))
                effective_dpi = "600 (simulated {})".format(ui.resolution_dpi)
            else:
                final_pixel_size = scaled_pixel_size
                effective_dpi = str(ui.resolution_dpi)
            
            ui.log('Exporting frame {} to folder {} with DPI={}, pixel_size={}, scale={}, final_size={}'.format(
                i, ui.folder, effective_dpi, ui.pixel_size, ui.scale_factor, final_pixel_size))
            export_frame(doc, view, ui.folder, i, ui.resolution_dpi, ui.pixel_size, ui.scale_factor)
            ui.progressBar.Value = i + 1
        ui.log('Animation finished! Done! Frames created: {}'.format(ui.frames))
        # --- Create GIF if checkbox is checked ---
        try:
            create_gif_checked = bool(getattr(ui.createGifCheckBox, 'IsChecked', False))
            ui.log('Create GIF checkbox state: {}'.format(create_gif_checked))
            
            if create_gif_checked:
                ui.log('Creating GIF as requested...')
                ui.OnCreateGif(None, None)
            else:
                ui.log('Create GIF checkbox not checked, skipping GIF creation')
        except Exception as e:
            ui.log('Error checking create GIF checkbox: {}'.format(e))
    except Exception as e:
        ui.log('CRITICAL ERROR in animation: {}'.format(e))
        import traceback
        ui.log('Traceback:')
        ui.log(traceback.format_exc())
    finally:
        ui.progressBar.Visibility = Visibility.Collapsed

def animate():
    try:
        if DEBUG_PRINT:
            print("Starting animate() function")
        ui = ParamUI()
        if DEBUG_PRINT:
            print("UI created, showing dialog...")
        ui.ShowDialog()  # Only show window, no run_animation(ui) here!
    except Exception as e:
        if DEBUG_PRINT:
            print("CRITICAL ERROR in animate(): {}".format(e))
            import traceback
            print("Traceback:")
            print(traceback.format_exc())

if __name__ == '__main__':
    animate()
